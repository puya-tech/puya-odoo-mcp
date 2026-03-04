import json
import logging
import time

logger = logging.getLogger("puya_odoo_mcp.audit")


class AuditLogger:
    def __init__(self, user: str, role: str):
        self.user = user
        self.role = role

    def log(self, action: str, model: str, details: dict | None = None,
            duration_ms: float | None = None):
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "user": self.user,
            "role": self.role,
            "action": action,
            "model": model,
        }
        if details:
            entry["details"] = details
        if duration_ms is not None:
            entry["duration_ms"] = round(duration_ms, 2)
        logger.info(json.dumps(entry))
