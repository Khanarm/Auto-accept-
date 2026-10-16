import os
import json
import logging
import urllib.request
import urllib.error

from http.server import BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/yourchannel")
WELCOME_MESSAGE = os.environ.get(
    "WELCOME_MESSAGE",
    "🎉 Welcome! Your join request has been approved."
)


def telegram_api(method, payload):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as exc:
        error = exc.read().decode("utf-8", errors="replace")
        logger.error("Telegram API error: %s", error)
        return {"ok": False, "description": error}

    except Exception:
        logger.exception("Telegram API request failed")
        return {"ok": False, "description": "Request failed"}


def process_update(update):
    chat_member = update.get("chat_join_request")

    if not chat_member:
        return

    chat = chat_member.get("chat", {})
    user = chat_member.get("from", {})
    user_id = user.get("id")

    if not user_id:
        return

    # Join request updates can contain user_chat_id.
    # Telegram permits messaging this chat during the
    # documented 5-minute window while the request is pending.
    user_chat_id = chat_member.get("user_chat_id")

    if user_chat_id:
        message = (
            f"{WELCOME_MESSAGE}\n\n"
            f"📢 Channel: {CHANNEL_LINK}"
        )

        telegram_api(
            "sendMessage",
            {
                "chat_id": user_chat_id,
                "text": message,
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {
                                "text": "📢 Join Channel",
                                "url": CHANNEL_LINK,
                            }
                        ]
                    ]
                },
            },
        )

    # Approve the request after attempting the DM.
    result = telegram_api(
        "approveChatJoinRequest",
        {
            "chat_id": chat.get("id"),
            "user_id": user_id,
        },
    )

    if result.get("ok"):
        logger.info("Approved join request for user %s", user_id)
    else:
        logger.error("Could not approve join request: %s", result)


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        if not WEBHOOK_SECRET:
            self.send_error(500, "Webhook secret is not configured")
            return

        received_secret = self.headers.get(
            "X-Telegram-Bot-Api-Secret-Token", ""
        )

        if received_secret != WEBHOOK_SECRET:
            self.send_error(403, "Invalid webhook secret")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))

            if length <= 0 or length > 1024 * 1024:
                self.send_error(400, "Invalid request body")
                return

            update = json.loads(self.rfile.read(length).decode("utf-8"))
            process_update(update)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        except Exception:
            logger.exception("Failed to process update")
            self.send_error(500, "Internal server error")

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"running"}')
