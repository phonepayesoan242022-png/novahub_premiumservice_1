# Nova Hub — Render Deployment Guide (မြန်မာလို)

ဒီ package က Nova Hub FastAPI website/backend ကို Render မှာတင်ဖို့ ပြင်ဆင်ထားပါတယ်။ `Dockerfile` က Render ရဲ့ `PORT` environment variable ကိုဖတ်ပြီး `0.0.0.0` မှာ listen လုပ်ပါတယ်။

## 1) GitHub Repository ဖန်တီးပါ

1. https://github.com ကိုဖွင့်ပြီး sign in ဝင်ပါ။
2. New repository ကိုနှိပ်ပြီး `nova-hub-store` လို့ ဖန်တီးပါ။ Private repository သုံးနိုင်ပါတယ်။
3. ZIP ထဲက `nova_hub_backend` folder ကိုဖွင့်ပါ။ အဲဒီထဲက `app.py`, `requirements.txt`, `Dockerfile`, `.gitignore`, `.env.example`, `check_telegram.py`, `public/` တို့ကို repository root ထဲတင်ပါ။
4. `.env` နဲ့ `private_data/` ကို GitHub မတင်ပါနဲ့။ Bot token ကို code ထဲ မရေးပါနဲ့။

## 2) Render မှာ Web Service တည်ဆောက်ပါ

1. https://render.com ကိုဖွင့်ပြီး account ဝင်/ဖွင့်ပါ။
2. Dashboard → **New +** → **Web Service** ကိုရွေးပါ။
3. GitHub repository `nova-hub-store` ကို connect လုပ်ပြီး Select လုပ်ပါ။
4. Root Directory ကို blank ထားပါ (Dockerfile နဲ့ app.py repository root မှာ ရှိရပါမယ်)။
5. Runtime / Environment ကို Docker (Dockerfile detected) ဖြစ်ကြောင်းစစ်ပါ။
6. Health Check Path ကို `/api/health` ထည့်ပါ။
7. Create Web Service / Deploy ကိုနှိပ်ပါ။

## 3) Environment Variables ထည့်ပါ

Render ရဲ့ service page → **Environment** → **Add Environment Variable** မှာ အောက်က variables တွေ တစ်ခုချင်းစီ ထည့်ပါ။

- `TELEGRAM_BOT_TOKEN` = BotFather ကရတဲ့ TOKEN အသစ် အပြည့်အစုံ
- `TELEGRAM_ADMIN_CHAT_ID` = `5691418980`
- `ADMIN_PASSWORD` = ခိုင်မာတဲ့ admin password (local testing မှာသုံးခဲ့တဲ့ 200521 ကို public မှာမသုံးဖို့ အကြံပြုပါတယ်)
- `SESSION_SECRET` = ကြိုတင်ခန့်မှန်းမရတဲ့ random secret အရှည် 32 လုံးကျော်
- `COOKIE_SECURE` = `true`
- `DATA_DIR` = `/var/data`

Token ကို `.env.example`, HTML, GitHub repository, screenshot တို့မှာ မထည့်ပါနဲ့။

SESSION_SECRET ဖန်တီးရန် Windows Command Prompt မှာ ဒီ command ကို run လုပ်နိုင်ပါတယ်:

```bat
py -c "import secrets; print(secrets.token_urlsafe(48))"
```

ထွက်လာတဲ့ random text ကို Render Environment ထဲက `SESSION_SECRET` value အဖြစ်သုံးပါ။

## 4) Persistent Disk ထည့်ပါ (အရေးကြီး)

ဒီ backend က SQLite database နဲ့ uploaded receipt/payment screenshots ကို ဖိုင်အဖြစ် သိမ်းတာကြောင့် ephemeral storage မလုံလောက်ပါဘူး။ Render docs အရ Persistent Disk ကို paid web service မှာပဲ attach လုပ်နိုင်ပါတယ်.

1. Render service → **Disks** (သို့) service settings မှာ **Add Disk** ကိုရွေးပါ။
2. Name ကို `nova-hub-data` လို့ပေးပါ။
3. Mount Path ကို `/var/data` ထည့်ပါ။
4. လိုအပ်သလောက် disk size ရွေးပြီး Save လုပ်ပါ။
5. Deploy ပြီး health check ကို အောင်မြင်ကြောင်းစစ်ပါ။

Disk မထည့်ထားပါက deploy/restart ပြီးတဲ့အခါ Order Database နဲ့ Receipt files ပျောက်နိုင်တာကြောင့် တကယ့် order အတွက် မသုံးပါနဲ့။ Free instance မှာ Persistent Disk မရနိုင်ပါ; အသုံးမပြုခင် Render ရဲ့ current pricing ကို စစ်ပါ။

## 5) Public URL ဖွင့်ပါ

Render service → **Settings** → **Networking** → **Generate Domain** ကိုနှိပ်ပါ။ Deploy success ဖြစ်ပြီးနောက် `https://...onrender.com` link ကို Customer တွေဆီ ပေးနိုင်ပါတယ်.

ဒီ link ကိုဖွင့်ပါ။ Health စစ်ရန် `https://YOUR-DOMAIN/api/health` ကိုဖွင့်ပြီး `{"ok":true,...}` ရကြောင်းစစ်ပါ။

## 6) Telegram test

1. Environment ထဲက `TELEGRAM_BOT_TOKEN` မှန်ကန်ပြီး `TELEGRAM_ADMIN_CHAT_ID=5691418980` ဖြစ်ကြောင်းစစ်ပါ။
2. Telegram မှာ ကိုယ်ဖန်တီးထားတဲ့ Nova Hub bot ကို `/start` လုပ်ထားပါ။
3. Environment ပြင်ပြီးရင် Save/Deploy လုပ်ပါ။
4. Public site မှာ order အသစ်တင်ပြီး Admin chat ထဲ Receipt နှင့် payment proof ပုံပို့ရောက်မရောက်စစ်ပါ။
5. Render **Logs** မှာ error စစ်ပါ။

## Limits and safety

- Payment receipt image is stored privately and served through authenticated admin endpoints.
- Telegram message send can fail independently of order storage. Test the bot and chat ID.
- This app does not verify bank transfers automatically. Admin should inspect payment proof before marking Paid/Completed.
- Product/price/stock/promotion/payment/slideshow settings currently use browser localStorage in the frontend. That means admin changes are not synchronized to every visitor/browser. Before relying on this for real public sales, these settings should be moved to server-side database/API.
- Use HTTPS, long admin password, unique session secret, secure bot token handling, persistent backups, and never commit `.env` or `private_data/`.
