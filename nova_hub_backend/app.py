import asyncio
import html as html_lib
import os
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "private_data"))).resolve()
UPLOAD_ROOT = DATA_DIR / "receipts"
DB_PATH = DATA_DIR / "orders.sqlite3"
PUBLIC_DIR = BASE_DIR / "public"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "200521")
SESSION_SECRET = os.getenv("SESSION_SECRET", "CHANGE_THIS_SECRET_BEFORE_PUBLIC_DEPLOYMENT")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
ORDER_STATUSES = {"Pending", "Paid", "Completed", "Cancelled"}

app = FastAPI(title="Nova Hub Order API", version="1.0.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="nova_hub_admin",
    max_age=8 * 60 * 60,
    same_site="lax",
    https_only=COOKIE_SECURE,
)

login_attempts = {}

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def db_connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(DATA_DIR, 0o700)
        os.chmod(UPLOAD_ROOT, 0o700)
    except OSError:
        pass
    with db_connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            buyer_name TEXT NOT NULL,
            buyer_contact TEXT NOT NULL,
            product_name TEXT NOT NULL,
            variant TEXT NOT NULL DEFAULT '',
            price INTEGER NOT NULL CHECK(price >= 0),
            payment_name TEXT NOT NULL,
            payment_account TEXT NOT NULL,
            payment_owner TEXT NOT NULL DEFAULT '',
            transaction_id TEXT NOT NULL DEFAULT '',
            transfer_time TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            proof_path TEXT NOT NULL,
            receipt_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            notification_sent INTEGER NOT NULL DEFAULT 0,
            notification_error TEXT NOT NULL DEFAULT ''
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")

@app.on_event("startup")
def on_startup():
    init_db()

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/admin") else "no-cache"
    return response

def require_admin(request: Request):
    if not request.session.get("is_admin"):
        raise HTTPException(status_code=401, detail="Admin login လိုအပ်ပါတယ်။")

def image_extension(data: bytes) -> Optional[str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    return None

async def save_upload(upload: UploadFile, folder: Path, stem: str) -> Path:
    if not upload:
        raise HTTPException(status_code=400, detail="Payment screenshot နဲ့ Receipt ပုံ နှစ်ခုလုံးလိုအပ်ပါတယ်။")
    data = await upload.read(MAX_IMAGE_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail=f"{stem} ပုံဖိုင် အလွတ်ဖြစ်နေပါတယ်။")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail=f"{stem} ပုံဖိုင်ကို 8MB အောက် လျှော့ပါ။")
    ext = image_extension(data)
    if not ext:
        raise HTTPException(status_code=415, detail=f"{stem} သည် PNG, JPG, WEBP, GIF ပုံဖြစ်ရပါမယ်။")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / f"{stem}{ext}"
    with path.open("xb") as f:
        f.write(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path

def telegram_api_call(method: str, data: dict, image_path: Optional[Path] = None):
    if not BOT_TOKEN or BOT_TOKEN.lower().startswith(("paste_", "replace_", "your_")):
        return False, "TELEGRAM_BOT_TOKEN is not configured"
    if not ADMIN_CHAT_ID:
        return False, "TELEGRAM_ADMIN_CHAT_ID is not configured"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        if image_path:
            with image_path.open("rb") as image_file:
                response = requests.post(
                    url, data=data,
                    files={"photo": (image_path.name, image_file, "image/png" if image_path.suffix == ".png" else "image/jpeg")},
                    timeout=20
                )
        else:
            response = requests.post(url, json=data, timeout=12)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            return False, "Telegram API rejected the request"
        return True, ""
    except Exception as exc:
        # Do not include request URLs/exceptions; URLs contain the bot token.
        return False, type(exc).__name__

def notify_admin(order: dict, receipt_path: Path, proof_path: Path):
    name = html_lib.escape(order["buyer_name"])
    contact = html_lib.escape(order["buyer_contact"])
    product = html_lib.escape(order["product_name"])
    variant = html_lib.escape(order["variant"])
    payment = html_lib.escape(order["payment_name"])
    account = html_lib.escape(order["payment_account"])
    owner = html_lib.escape(order["payment_owner"])
    txn = html_lib.escape(order["transaction_id"] or "မထည့်ထားပါ")
    note = html_lib.escape(order["note"] or "—")
    caption = (
        "🔔 <b>NEW NOVA HUB ORDER</b>\n"
        f"<b>Order ID:</b> <code>{html_lib.escape(order['id'])}</code>\n"
        f"<b>Status:</b> Pending\n"
        f"<b>Product:</b> {product}\n"
        f"<b>Plan:</b> {variant}\n"
        f"<b>Price:</b> {order['price']:,} Ks\n"
        f"<b>Customer:</b> {name}\n"
        f"<b>Contact:</b> {contact}\n"
        f"<b>Payment:</b> {payment} — {account}\n"
        f"<b>Account Name:</b> {owner}\n"
        f"<b>Transaction ID:</b> {txn}\n"
        f"<b>Note:</b> {note}\n\n"
        "Receipt ပုံနှင့် ငွေလွှဲပြေစာကို ပူးတွဲပို့ထားပါတယ်။ Admin Dashboard မှာ Status ပြောင်းနိုင်ပါတယ်။"
    )
    ok1, error1 = telegram_api_call("sendPhoto", {
        "chat_id": ADMIN_CHAT_ID,
        "caption": caption[:1024],
        "parse_mode": "HTML",
    }, receipt_path)
    ok2, error2 = telegram_api_call("sendPhoto", {
        "chat_id": ADMIN_CHAT_ID,
        "caption": f"💳 Payment proof — Order {order['id']}",
    }, proof_path)
    if ok1 and ok2:
        return True, ""
    errors = [e for e in (error1, error2) if e]
    return False, ", ".join(errors)[:180] or "Telegram notification failed"

class AdminLogin(BaseModel):
    password: str = Field(min_length=1, max_length=128)

class StatusUpdate(BaseModel):
    status: str

@app.get("/api/health")
def health():
    return {"ok": True, "service": "nova-hub-order-api", "time": utc_now()}

@app.post("/api/admin/login")
async def admin_login(payload: AdminLogin, request: Request):
    client = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc).timestamp()
    history = [t for t in login_attempts.get(client, []) if now - t < 300]
    if len(history) >= 8:
        login_attempts[client] = history
        raise HTTPException(status_code=429, detail="Login အကြိမ်များလွန်းပါတယ်။ ၅ မိနစ်နောက် ပြန်စမ်းပါ။")
    history.append(now)
    login_attempts[client] = history
    if not secrets.compare_digest(payload.password, ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="PIN / Password မှားနေပါတယ်။")
    request.session.clear()
    request.session["is_admin"] = True
    request.session["login_at"] = utc_now()
    login_attempts.pop(client, None)
    return {"ok": True}

@app.post("/api/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return {"ok": True}

@app.get("/api/admin/me")
def admin_me(request: Request):
    require_admin(request)
    return {"ok": True, "is_admin": True}

@app.post("/api/orders", status_code=201)
async def create_order(
    request: Request,
    order_id: str = Form(..., max_length=40),
    buyer_name: str = Form(..., max_length=80),
    buyer_contact: str = Form(..., max_length=100),
    product_name: str = Form(..., max_length=160),
    variant: str = Form("", max_length=160),
    price: int = Form(..., ge=0, le=100_000_000),
    payment_name: str = Form(..., max_length=80),
    payment_account: str = Form(..., max_length=100),
    payment_owner: str = Form("", max_length=100),
    transaction_id: str = Form("", max_length=100),
    transfer_time: str = Form("", max_length=100),
    note: str = Form("", max_length=1000),
    payment_proof: UploadFile = File(...),
    receipt_file: UploadFile = File(...),
):
    if not re.fullmatch(r"NH-[A-Z0-9]{3,30}", order_id):
        raise HTTPException(status_code=400, detail="Order ID format မမှန်ပါ။")
    if not buyer_name.strip() or not buyer_contact.strip() or not product_name.strip():
        raise HTTPException(status_code=400, detail="Customer နဲ့ Product အချက်အလက်များ ဖြည့်ပါ။")
    order_folder = UPLOAD_ROOT / uuid.uuid4().hex
    order_folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    saved_paths = []
    try:
        proof_path = await save_upload(payment_proof, order_folder, "payment-proof")
        saved_paths.append(proof_path)
        receipt_path = await save_upload(receipt_file, order_folder, "receipt")
        saved_paths.append(receipt_path)
        created = utc_now()
        with db_connect() as conn:
            conn.execute("""
                INSERT INTO orders (
                    id,buyer_name,buyer_contact,product_name,variant,price,
                    payment_name,payment_account,payment_owner,transaction_id,
                    transfer_time,note,proof_path,receipt_path,status,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                order_id, buyer_name.strip(), buyer_contact.strip(), product_name.strip(), variant.strip(),
                int(price), payment_name.strip(), payment_account.strip(), payment_owner.strip(),
                transaction_id.strip(), transfer_time.strip(), note.strip(),
                str(proof_path.resolve()), str(receipt_path.resolve()), "Pending", created, created
            ))
        order = {
            "id": order_id, "buyer_name": buyer_name.strip(), "buyer_contact": buyer_contact.strip(),
            "product_name": product_name.strip(), "variant": variant.strip(), "price": int(price),
            "payment_name": payment_name.strip(), "payment_account": payment_account.strip(),
            "payment_owner": payment_owner.strip(), "transaction_id": transaction_id.strip(),
            "transfer_time": transfer_time.strip(), "note": note.strip()
        }
        notified, notification_error = await run_in_threadpool(notify_admin, order, receipt_path, proof_path)
        with db_connect() as conn:
            conn.execute("UPDATE orders SET notification_sent=?, notification_error=?, updated_at=? WHERE id=?",
                         (1 if notified else 0, notification_error, utc_now(), order_id))
        return {
            "ok": True, "order_id": order_id, "status": "Pending",
            "notification_sent": notified,
            "notification_message": "Admin notified" if notified else "Order saved; Telegram notification needs configuration"
        }
    except sqlite3.IntegrityError:
        for path in saved_paths:
            try: path.unlink(missing_ok=True)
            except OSError: pass
        raise HTTPException(status_code=409, detail="ဒီ Order ID ရှိပြီးသားဖြစ်နေပါတယ်။ ထပ်မံ Order တင်ပါ။")
    except HTTPException:
        for path in saved_paths:
            try: path.unlink(missing_ok=True)
            except OSError: pass
        raise
    except Exception as exc:
        for path in saved_paths:
            try: path.unlink(missing_ok=True)
            except OSError: pass
        raise HTTPException(status_code=500, detail="Order ကို သိမ်းဆည်းမရပါ။ Server log ကို Admin က စစ်ပါ။")

@app.get("/api/admin/orders")
def list_orders(request: Request, limit: int = 50):
    require_admin(request)
    limit = min(max(limit, 1), 200)
    with db_connect() as conn:
        rows = conn.execute("""
            SELECT id,buyer_name,buyer_contact,product_name,variant,price,payment_name,
                   transaction_id,status,created_at,updated_at,notification_sent
            FROM orders ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()
    return {"orders": [dict(row) for row in rows]}

@app.patch("/api/admin/orders/{order_id}/status")
def update_order_status(order_id: str, payload: StatusUpdate, request: Request):
    require_admin(request)
    if payload.status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Status ကို Pending, Paid, Completed, Cancelled တို့ထဲမှ ရွေးပါ။")
    with db_connect() as conn:
        row = conn.execute("SELECT id FROM orders WHERE id=?", (order_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order မတွေ့ပါ။")
        conn.execute("UPDATE orders SET status=?,updated_at=? WHERE id=?", (payload.status, utc_now(), order_id))
    return {"ok": True, "order_id": order_id, "status": payload.status}

@app.get("/api/admin/orders/{order_id}/files/{kind}")
def get_order_file(order_id: str, kind: str, request: Request):
    require_admin(request)
    if kind not in {"receipt", "proof"}:
        raise HTTPException(status_code=404, detail="ဖိုင်မတွေ့ပါ။")
    with db_connect() as conn:
        row = conn.execute("SELECT receipt_path,proof_path FROM orders WHERE id=?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Order မတွေ့ပါ။")
    path = Path(row["receipt_path"] if kind == "receipt" else row["proof_path"]).resolve()
    if UPLOAD_ROOT.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="ဖိုင်မတွေ့ပါ။")
    media = "image/png" if path.suffix.lower() == ".png" else ("image/webp" if path.suffix.lower() == ".webp" else ("image/gif" if path.suffix.lower() == ".gif" else "image/jpeg"))
    return FileResponse(path, media_type=media, filename=f"{order_id}-{kind}{path.suffix}", content_disposition_type="inline")

# Serve the HTML from the same origin, so API calls and the authenticated cookie work.
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public")
