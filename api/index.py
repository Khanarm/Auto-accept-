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
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "")
WELCOME_MESSAGE = os.environ.get(
    "WELCOME_MESSAGE",
    "🎉 Welcome! Your join request has been received."
)


def telegram_api(method, payload):
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is missing")
        return {"ok": False, "description": "BOT_TOKEN missing"}

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
            result = json.loads(response.read().decode("utf-8"))

        if not result.get("ok"):
            logger.error(
                "Telegram API %s failed: %s",
                method,
                result.get("description"),
            )
        else:
            logger.info("Telegram API %s succeeded", method)

        return result

    except urllib.error.HTTPError as exc:
        error = exc.read().decode("utf-8", errors="replace")
        logger.error("Telegram API %s HTTP error: %s", method, error)
        return {"ok": False, "description": error}

    except Exception:
        logger.exception("Telegram API %s request failed", method)
        return {"ok": False, "description": "Request failed"}


def process_update(update):
    join_request = update.get("chat_join_request")

    if not join_request:
        logger.info("Update received without a join request")
        return

    chat = join_request.get("chat", {})
    user = join_request.get("from", {})

    chat_id = chat.get("id")
    user_id = user.get("id")
    user_chat_id = join_request.get("user_chat_id")

    if chat_id is None or user_id is None:
        logger.error("Join request is missing chat_id or user_id")
        return

    logger.info(
        "Join request received: chat_id=%s user_id=%s",
        chat_id,
        user_id,
    )

    # Try to send the DM while the request is pending.
    if user_chat_id:
        message = WELCOME_MESSAGE

        if CHANNEL_LINK:
            message += f"\n\n📢 Channel: {CHANNEL_LINK}"

        payload = {
            "chat_id": user_chat_id,
            "text": message,
        }

        if CHANNEL_LINK.startswith(("https://t.me/", "http://t.me/")):
            payload["reply_markup"] = {
                "inline_keyboard": [[
                    {
                        "text": "📢 Open Channel",
                        "url": CHANNEL_LINK,
                    }
                ]]
            }

        dm_result = telegram_api("sendMessage", payload)

        if not dm_result.get("ok"):
            logger.warning(
                "DM failed for user %s: %s",
                user_id,
                dm_result.get("description"),
            )
    else:
        logger.warning("No user_chat_id available for user %s", user_id)

    # Approve the request regardless of whether DM succeeded.
    approval = telegram_api(
        "approveChatJoinRequest",
        {
            "chat_id": chat_id,
            "user_id": user_id,
        },
    )

    if approval.get("ok"):
        logger.info("Join request approved for user %s", user_id)
    else:
        logger.error(
            "Approval failed for user %s: %s",
            user_id,
            approval.get("description"),
        )


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"running"}')

    def do_POST(self):
        if not BOT_TOKEN or not WEBHOOK_SECRET:
            self.send_error(500, "Required environment variables are missing")
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

            body = self.rfile.read(length)
            update = json.loads(body.decode("utf-8"))

            process_update(update)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        except Exception:
            logger.exception("Webhook processing failed")
            self.send_error(500, "Internal server error")
