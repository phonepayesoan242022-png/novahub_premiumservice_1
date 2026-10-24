from pathlib import Path
import os
import sys
import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
chat_id = (os.getenv("TELEGRAM_ADMIN_CHAT_ID") or "").strip()

print("=" * 58)
print("NOVA HUB - TELEGRAM BOT CONNECTION CHECK")
print("=" * 58)

if not token or token.lower().startswith(("paste_", "replace_", "your_")):
    print("[FAIL] TELEGRAM_BOT_TOKEN is empty or still a placeholder.")
    print("Open .env in this folder and paste the full NEW token from BotFather.")
    sys.exit(1)

if not chat_id or chat_id.lower().startswith(("paste_", "replace_", "your_")):
    print("[FAIL] TELEGRAM_ADMIN_CHAT_ID is empty.")
    print("Put the correct numeric admin chat ID in .env.")
    sys.exit(1)

print("[INFO] Checking bot token with Telegram...")
try:
    response = requests.get(
        f"https://api.telegram.org/bot{token}/getMe",
        timeout=15
    )
    try:
        result = response.json()
    except ValueError:
        print(f"[FAIL] Telegram returned a non-JSON response (HTTP {response.status_code}).")
        sys.exit(1)
except requests.RequestException as exc:
    print("[FAIL] Could not connect to Telegram. Check internet/proxy/firewall.")
    print("Error type:", type(exc).__name__)
    print("The bot token was not printed.")
    sys.exit(1)

if response.status_code != 200 or not result.get("ok"):
    print(f"[FAIL] Bot token rejected (HTTP {response.status_code}).")
    print("Telegram response:", result.get("description", "No description returned"))
    print("Get/revoke the token in @BotFather and update TELEGRAM_BOT_TOKEN in .env.")
    print("The token itself was not printed.")
    sys.exit(1)

bot = result.get("result", {})
print("[OK] Bot token works.")
print("Bot username:", "@" + bot.get("username", "(unknown)"))
print("Configured admin chat ID:", chat_id)

print()
print("[INFO] Sending a test message to the configured admin chat...")
try:
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": "✅ Nova Hub test message. Telegram bot token and admin chat ID are working."
        },
        timeout=15
    )
    try:
        result = response.json()
    except ValueError:
        print(f"[FAIL] Telegram returned a non-JSON response (HTTP {response.status_code}).")
        sys.exit(1)
except requests.RequestException as exc:
    print("[FAIL] Could not send message. Check internet/proxy/firewall.")
    print("Error type:", type(exc).__name__)
    print("The bot token was not printed.")
    sys.exit(1)

if response.status_code == 200 and result.get("ok"):
    print("[OK] Test message sent successfully.")
    print("Open Telegram and check the chat with your Nova Hub bot.")
    print("Now stop the website server with Ctrl+C, start it again, then submit a new test order.")
else:
    print(f"[FAIL] Telegram could not send to this chat (HTTP {response.status_code}).")
    description = result.get("description", "No description returned")
    print("Telegram response:", description)
    low = description.lower()
    if "chat not found" in low:
        print("FIX: Open your own Nova Hub bot in Telegram, press Start or send /start,")
        print("then verify TELEGRAM_ADMIN_CHAT_ID in .env. Do not use @BotFather as the destination.")
    elif "bot was blocked" in low:
        print("FIX: Unblock your Nova Hub bot in Telegram and send /start.")
    elif "unauthorized" in low:
        print("FIX: Token is invalid/revoked. Put the current full token from BotFather in .env.")
    else:
        print("FIX: Follow Telegram's response above. Keep the token private.")
    sys.exit(1)

print("=" * 58)
