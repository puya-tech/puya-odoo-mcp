import json
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("puya_odoo_mcp.audit")


class AuditLogger:
    def __init__(self, user: str, role: str,
                 supabase_url: str | None = None,
                 supabase_key: str | None = None):
        self.user = user
        self.role = role
        self._supabase_url = supabase_url
        self._supabase_key = supabase_key
        self._table = "mcp_audit_log"

    @property
    def _enabled(self) -> bool:
        return bool(self._supabase_url and self._supabase_key)

    def _headers(self) -> dict:
        return {
            "apikey": self._supabase_key,
            "Authorization": f"Bearer {self._supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _request(self, method: str, path: str, body: dict | None = None,
                 params: str = "") -> list | dict | None:
        url = f"{self._supabase_url}/rest/v1/{path}"
        if params:
            url += f"?{params}"
        data = json.dumps(body, default=str).encode() if body else None
        req = Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except (HTTPError, URLError, TimeoutError) as e:
            logger.warning(f"Audit log failed ({method} {path}): {e}")
            return None

    def log(self, action: str, model: str, details: dict | None = None,
            duration_ms: float | None = None):
        """Log a read-only action (search, count, fields_get). Only to logger, not DB."""
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

    def log_mutation(self, action: str, model: str, record_ids: list,
                     old_values: list | None, new_values: dict | list | None,
                     details: dict | None = None,
                     duration_ms: float | None = None) -> int | None:
        """Log a mutation (write/create/delete/execute) with before/after snapshot."""
        # Always log to stdout
        self.log(action, model, details, duration_ms)

        if not self._enabled:
            logger.warning("Supabase not configured — mutation not persisted to audit DB")
            return None

        row = {
            "user_login": self.user,
            "role": self.role,
            "action": action,
            "model": model,
            "record_ids": record_ids,
            "old_values": old_values,
            "new_values": new_values,
            "details": details,
            "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
        }

        result = self._request("POST", self._table, row)
        if result and isinstance(result, list) and len(result) > 0:
            return result[0].get("id")
        return None

    def get_log(self, audit_id: int) -> dict | None:
        """Get a single audit entry by ID."""
        if not self._enabled:
            return None
        result = self._request("GET", self._table, params=f"id=eq.{audit_id}")
        if result and isinstance(result, list) and len(result) > 0:
            return result[0]
        return None

    def query_logs(self, model: str | None = None, action: str | None = None,
                   user: str | None = None, limit: int = 50) -> list:
        """Query audit logs with optional filters."""
        if not self._enabled:
            return []

        params = ["order=created_at.desc", f"limit={limit}"]
        if model:
            params.append(f"model=eq.{model}")
        if action:
            params.append(f"action=eq.{action}")
        if user:
            params.append(f"user_login=eq.{user}")

        result = self._request("GET", self._table, params="&".join(params))
        return result if isinstance(result, list) else []

    def query_past_sessions(
        self,
        entity_type: str | None = None,
        entity_id: str | None = None,
        channel_type: str | None = None,
        channel_id: str | None = None,
        thread_id: str | None = None,
        limit: int = 5,
        offset: int = 0,
    ) -> list:
        """Query archived agent sessions. Channel-agnostic.

        Filter by entity (entity_type + entity_id) or by channel/thread.
        Returns archived sessions with summary_text and summary_data.
        """
        if not self._enabled:
            return []

        params = [
            "status=eq.archived",
            "order=archived_at.desc",
            f"limit={limit}",
            f"offset={offset}",
            "select=id,channel_type,channel_id,thread_id,business_entity_type,"
            "business_entity_id,created_at,archived_at,summary_text,summary_data,participants",
        ]
        if entity_type:
            params.append(f"business_entity_type=eq.{entity_type}")
        if entity_id:
            params.append(f"business_entity_id=eq.{entity_id}")
        if channel_type:
            params.append(f"channel_type=eq.{channel_type}")
        if channel_id:
            params.append(f"channel_id=eq.{channel_id}")
        if thread_id:
            params.append(f"thread_id=eq.{thread_id}")

        result = self._request("GET", "agent_sessions", params="&".join(params))
        return result if isinstance(result, list) else []

    def mark_reverted(self, audit_id: int, reverted_by: str) -> bool:
        """Mark an audit entry as reverted."""
        if not self._enabled:
            return False
        result = self._request(
            "PATCH", self._table,
            body={
                "reverted": True,
                "reverted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "reverted_by": reverted_by,
            },
            params=f"id=eq.{audit_id}",
        )
        return result is not None

    # ── Pending actions (two-phase commit) ──────────────────────────────

    def create_pending(self, action: str, model: str, record_ids: list,
                       old_values: list | None, new_values: dict | list | None,
                       preview: str, is_massive: bool,
                       record_count: int, details: dict | None = None,
                       expiry_minutes: int = 10,
                       status: str = "pending") -> int | None:
        """Store a pending action for preview/confirmation."""
        if not self._enabled:
            return None

        row = {
            "user_login": self.user,
            "role": self.role,
            "status": status,
            "action": action,
            "model": model,
            "record_ids": record_ids,
            "old_values": old_values,
            "new_values": new_values,
            "preview": preview,
            "is_massive": is_massive,
            "record_count": record_count,
            "details": details,
        }

        result = self._request("POST", "mcp_pending_actions", row)
        if result and isinstance(result, list) and len(result) > 0:
            return result[0].get("id")
        return None

    def get_pending(self, pending_id: int) -> dict | None:
        """Get a pending action by ID."""
        if not self._enabled:
            return None
        result = self._request(
            "GET", "mcp_pending_actions",
            params=f"id=eq.{pending_id}",
        )
        if result and isinstance(result, list) and len(result) > 0:
            return result[0]
        return None

    def confirm_pending(self, pending_id: int, audit_id: int | None) -> bool:
        """Mark a pending action as confirmed."""
        if not self._enabled:
            return False
        result = self._request(
            "PATCH", "mcp_pending_actions",
            body={
                "status": "confirmed",
                "confirmed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "audit_id": audit_id,
            },
            params=f"id=eq.{pending_id}&status=eq.pending",
        )
        return result is not None and len(result) > 0

    def update_pending_telegram_id(self, pending_id: int, telegram_message_id: int) -> bool:
        """Store the Telegram message ID on a pending action."""
        if not self._enabled:
            return False
        result = self._request(
            "PATCH", "mcp_pending_actions",
            body={"telegram_message_id": telegram_message_id},
            params=f"id=eq.{pending_id}",
        )
        return result is not None

    def cancel_pending(self, pending_id: int) -> bool:
        """Cancel a pending action."""
        if not self._enabled:
            return False
        result = self._request(
            "PATCH", "mcp_pending_actions",
            body={"status": "cancelled"},
            params=f"id=eq.{pending_id}&status=eq.pending",
        )
        return result is not None and len(result) > 0

    def query_pending(self, user: str | None = None, limit: int = 10) -> list:
        """Query pending actions."""
        if not self._enabled:
            return []
        params = ["status=eq.pending", "order=created_at.desc", f"limit={limit}"]
        if user:
            params.append(f"user_login=eq.{user}")
        result = self._request("GET", "mcp_pending_actions", params="&".join(params))
        return result if isinstance(result, list) else []
