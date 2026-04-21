import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("puya_odoo_mcp.slack")


class SlackNotifier:
    def __init__(self, bot_token: str | None = None, channel: str | None = None):
        self._bot_token = bot_token
        self._channel = channel

    @property
    def enabled(self) -> bool:
        return bool(self._bot_token and self._channel)

    def _api(self, method: str, body: dict) -> dict | None:
        if not self.enabled:
            return None
        url = f"https://slack.com/api/{method}"
        data = json.dumps(body).encode()
        req = Request(url, data=data, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._bot_token}",
        })
        try:
            with urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                if not result.get("ok"):
                    logger.warning(f"Slack API error ({method}): {result.get('error')}")
                return result
        except (HTTPError, URLError, TimeoutError) as e:
            logger.warning(f"Slack API error ({method}): {e}")
            return None

    def send_approval_request(self, pending_id: int, user: str, role: str,
                              action: str, model: str, record_count: int,
                              preview: str, reason: str | None = None,
                              target_env: str | None = None) -> str | None:
        """Send an approval request to the Slack channel. Returns message ts."""
        reason_line = f"\n:memo: Razón: \"{reason}\"" if reason else ""

        # Badge de entorno (staging/producción)
        if target_env == "production":
            env_badge = ":large_green_circle: *PRODUCCIÓN*"
        elif target_env:
            env_badge = f":warning: *{target_env.upper()}*"
        else:
            env_badge = ":grey_question: *entorno desconocido*"

        # Truncate preview for Slack
        if len(preview) > 1500:
            preview = preview[:1500] + "\n  ... (truncado)"

        text = (
            f":clipboard: *Solicitud de aprobación #{pending_id}*\n"
            f"{env_badge}\n"
            f"\n"
            f":bust_in_silhouette: Solicitante: {user} ({role}){reason_line}\n"
            f"\n"
            f":wrench: Acción: `{action}` en `{model}`\n"
            f":bar_chart: Registros: {record_count}\n"
            f"\n"
            f"```{preview}```"
        )

        result = self._api("chat.postMessage", {
            "channel": self._channel,
            "text": f"Solicitud de aprobación #{pending_id}",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                },
                {
                    "type": "actions",
                    "block_id": f"approval_{pending_id}",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "✅ Aprobar"},
                            "style": "primary",
                            "action_id": "approve_action",
                            "value": str(pending_id),
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "❌ Rechazar"},
                            "style": "danger",
                            "action_id": "reject_action",
                            "value": str(pending_id),
                        },
                    ],
                },
            ],
        })

        if result and result.get("ok"):
            return result.get("ts")
        return None

    def update_message_approved(self, message_ts: str, pending_id: int,
                                approved_by: str) -> None:
        """Update the approval message to show it was approved."""
        self._api("chat.update", {
            "channel": self._channel,
            "ts": message_ts,
            "text": f"✅ Solicitud #{pending_id} APROBADA por {approved_by}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"✅ *Solicitud #{pending_id} APROBADA Y EJECUTADA*\n\nAprobada por: {approved_by}",
                    },
                },
            ],
        })

    def update_message_rejected(self, message_ts: str, pending_id: int,
                                rejected_by: str) -> None:
        """Update the approval message to show it was rejected."""
        self._api("chat.update", {
            "channel": self._channel,
            "ts": message_ts,
            "text": f"❌ Solicitud #{pending_id} RECHAZADA por {rejected_by}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"❌ *Solicitud #{pending_id} RECHAZADA*\n\nRechazada por: {rejected_by}",
                    },
                },
            ],
        })
