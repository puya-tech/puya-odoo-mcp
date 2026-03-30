import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("puya_odoo_mcp.telegram")


class TelegramNotifier:
    def __init__(self, bot_token: str | None = None, chat_id: str | None = None):
        self._bot_token = bot_token
        self._chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    def _api(self, method: str, body: dict) -> dict | None:
        if not self.enabled:
            return None
        url = f"https://api.telegram.org/bot{self._bot_token}/{method}"
        data = json.dumps(body).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except (HTTPError, URLError, TimeoutError) as e:
            logger.warning(f"Telegram API error ({method}): {e}")
            return None

    def send_approval_request(self, pending_id: int, user: str, role: str,
                              action: str, model: str, record_count: int,
                              preview: str, reason: str | None = None) -> int | None:
        """Send an approval request to the Telegram group. Returns message_id."""
        reason_line = f"\n📝 Razón: \"{reason}\"" if reason else ""

        # Truncate preview for Telegram (max ~4096 chars)
        if len(preview) > 1500:
            preview = preview[:1500] + "\n  ... (truncado)"

        # Escape markdown special chars in preview
        preview_escaped = preview.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")

        text = (
            f"📋 *Solicitud de aprobación #{pending_id}*\n"
            f"\n"
            f"👤 Solicitante: {user} ({role}){reason_line}\n"
            f"\n"
            f"🔧 Acción: `{action}` en `{model}`\n"
            f"📊 Registros: {record_count}\n"
            f"\n"
            f"```\n{preview_escaped}\n```"
        )

        result = self._api("sendMessage", {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "✅ Aprobar", "callback_data": f"approve:{pending_id}"},
                    {"text": "❌ Rechazar", "callback_data": f"reject:{pending_id}"},
                ]]
            },
        })

        if result and result.get("ok"):
            return result["result"]["message_id"]
        return None

    def update_message_approved(self, message_id: int, pending_id: int,
                                approved_by: str) -> None:
        """Update the approval message to show it was approved."""
        self._api("editMessageText", {
            "chat_id": self._chat_id,
            "message_id": message_id,
            "text": f"✅ *Solicitud #{pending_id} APROBADA*\n\nAprobada por: {approved_by}",
            "parse_mode": "Markdown",
        })

    def update_message_rejected(self, message_id: int, pending_id: int,
                                rejected_by: str) -> None:
        """Update the approval message to show it was rejected."""
        self._api("editMessageText", {
            "chat_id": self._chat_id,
            "message_id": message_id,
            "text": f"❌ *Solicitud #{pending_id} RECHAZADA*\n\nRechazada por: {rejected_by}",
            "parse_mode": "Markdown",
        })
