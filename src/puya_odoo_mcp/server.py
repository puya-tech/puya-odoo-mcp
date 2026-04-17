import json
import logging
import time

from mcp.server.fastmcp import FastMCP

from .audit import AuditLogger
from .config import Config
from .odoo_client import OdooClient, OdooError
from .rbac import PermissionDenied, RBACEngine
from .telegram import TelegramNotifier
from .slack import SlackNotifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("puya_odoo_mcp")


def _serialize(obj) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


def _build_write_preview(model: str, old_records: list, new_values: dict) -> str:
    """Build a human-readable preview of what a write will change."""
    lines = [f"Cambios en {model} ({len(old_records)} registro{'s' if len(old_records) != 1 else ''}):\n"]

    for rec in old_records:
        rec_id = rec.get("id", "?")
        name = rec.get("name") or rec.get("display_name") or rec.get("x_name") or f"#{rec_id}"
        lines.append(f"  Registro #{rec_id} ({name}):")
        for field, new_val in new_values.items():
            old_val = rec.get(field, "—")
            if old_val != new_val:
                lines.append(f"    {field}: {_format_val(old_val)} -> {_format_val(new_val)}")
            else:
                lines.append(f"    {field}: {_format_val(old_val)} (sin cambio)")
        lines.append("")

    return "\n".join(lines)


def _build_create_preview(model: str, values: dict) -> str:
    """Build a human-readable preview of what will be created."""
    lines = [f"Crear nuevo registro en {model}:\n"]
    for field, val in values.items():
        lines.append(f"  {field}: {_format_val(val)}")
    return "\n".join(lines)


def _build_delete_preview(model: str, records: list) -> str:
    """Build a human-readable preview of what will be deleted."""
    lines = [f"Eliminar {len(records)} registro{'s' if len(records) != 1 else ''} de {model}:\n"]
    for rec in records:
        rec_id = rec.get("id", "?")
        name = rec.get("name") or rec.get("display_name") or f"#{rec_id}"
        lines.append(f"  #{rec_id} — {name}")
    return "\n".join(lines)


def _build_execute_preview(model: str, method: str, record_ids: list) -> str:
    """Build a human-readable preview of a method execution."""
    if record_ids:
        return f"Ejecutar {model}.{method}() en {len(record_ids)} registro{'s' if len(record_ids) != 1 else ''}: {record_ids}"
    return f"Ejecutar {model}.{method}()"


def _format_val(val) -> str:
    if val is False or val is None:
        return "(vacío)"
    if isinstance(val, list) and len(val) == 2 and isinstance(val[0], int):
        # Odoo many2one: [id, "display_name"]
        return str(val[1])
    if isinstance(val, list):
        if len(val) > 5:
            return f"[{len(val)} items]"
        return str(val)
    if isinstance(val, str) and len(val) > 100:
        return val[:100] + "..."
    return str(val)


def create_server() -> FastMCP:
    config = Config()
    client = OdooClient(config.odoo_url, config.odoo_db, config.odoo_login, config.odoo_api_key)
    uid = client.authenticate()
    role = client.get_user_role()

    user_info = client.execute_kw("res.users", "read", [[uid]], {"fields": ["login"]})
    username = user_info[0]["login"] if user_info else str(uid)

    logger.info(f"Authenticated as {username} (uid={uid}, role={role})")

    rbac = RBACEngine()
    audit = AuditLogger(
        user=username, role=role,
        supabase_url=config.supabase_url or None,
        supabase_key=config.supabase_key or None,
    )
    telegram = TelegramNotifier(
        bot_token=config.telegram_bot_token or None,
        chat_id=config.telegram_chat_id or None,
    )
    slack_notifier = SlackNotifier(
        bot_token=config.slack_bot_token or None,
        channel=config.slack_approval_channel or None,
    )

    def notify_approval(pending_id: int, action: str, model: str,
                        record_count: int, preview: str,
                        reason: str | None = None) -> tuple[str | int | None, str]:
        """Send approval notification to configured channel. Returns (msg_id, channel_type)."""
        if config.approval_channel == "slack" and slack_notifier.enabled:
            msg_id = slack_notifier.send_approval_request(
                pending_id=pending_id, user=username, role=role,
                action=action, model=model, record_count=record_count,
                preview=preview, reason=reason,
            )
            return msg_id, "slack"
        elif telegram.enabled:
            msg_id = telegram.send_approval_request(
                pending_id=pending_id, user=username, role=role,
                action=action, model=model, record_count=record_count,
                preview=preview, reason=reason,
            )
            return msg_id, "telegram"
        return None, "none"

    massive_threshold = rbac.massive_threshold
    expiry_minutes = rbac.pending_expiry_minutes

    env_label = config.environment.upper()

    mcp = FastMCP(
        "Odoo",
        instructions=(
            f"Odoo 16 MCP server. Environment: {env_label}. User: {username}, Role: {role}. "
            "Use odoo_search to query data, odoo_fields to inspect models. "
            "IMPORTANT: All write operations return a preview first. "
            "You MUST show the preview to the user and wait for their confirmation "
            "before calling odoo_confirm. Never confirm without user approval."
        ),
    )

    # ── Status & environment tools (all roles) ──────────────────────────

    @mcp.tool()
    def odoo_status() -> str:
        """Show current MCP connection status: environment, user, role, URL."""
        available_envs = [
            f.stem.replace("shared.", "").replace(".env", "") or "production"
            for f in sorted(Config.list_environments())
        ]
        return _serialize({
            "environment": config.environment,
            "odoo_url": config.odoo_url,
            "odoo_db": config.odoo_db,
            "user": username,
            "role": role,
            "uid": uid,
            "available_environments": available_envs,
            "supabase_connected": bool(config.supabase_url and config.supabase_key),
            "approval_channel": config.approval_channel,
            "telegram_connected": bool(config.telegram_bot_token and config.telegram_chat_id),
            "slack_connected": bool(config.slack_bot_token and config.slack_approval_channel),
        })

    @mcp.tool()
    def odoo_switch_env(environment: str) -> str:
        """[DEPRECATED] Switch environment is no longer needed.

        Use dual MCP instances instead — one for production, one for staging.
        Each instance gets its environment via ODOO_ENV (env var or credentials file).

        Args:
            environment: Ignored (deprecated)
        """
        return _serialize({
            "deprecated": True,
            "message": (
                "odoo_switch_env is deprecated. Use dual MCP instances instead: "
                "configure one MCP with ODOO_ENV=production and another with "
                "ODOO_ENV=staging. See README for setup instructions."
            ),
        })

    # ── Read-only tools (all roles) ─────────────────────────────────────

    @mcp.tool()
    def odoo_search(model: str, domain: list | None = None, fields: list | None = None,
                    limit: int = 80, offset: int = 0, order: str | None = None) -> str:
        """Search records in Odoo. Returns matching records with specified fields.

        Args:
            model: Odoo model name (e.g. 'res.partner', 'sale.order')
            domain: Search domain filter (e.g. [['is_company', '=', True]])
            fields: Fields to return (e.g. ['name', 'email']). Empty = all allowed.
            limit: Max records to return (default 80, max 200)
            offset: Number of records to skip
            order: Sort order (e.g. 'name asc, id desc')
        """
        t0 = time.time()
        try:
            perm = rbac.check_model_access(role, model, "search_read")
        except PermissionDenied as e:
            return f"Permission denied: {e}"

        domain = rbac.inject_domain(perm, domain or [], uid)
        if fields:
            fields = rbac.filter_fields(perm, fields)

        limit = min(limit, 200)
        kwargs = {"fields": fields or [], "limit": limit, "offset": offset}
        if order:
            kwargs["order"] = order

        try:
            result = client.execute_kw(model, "search_read", [domain], kwargs)
        except OdooError as e:
            return f"Odoo error: {e}"

        if perm.fields_denied and not fields:
            for record in result:
                for f in perm.fields_denied:
                    record.pop(f, None)

        duration = (time.time() - t0) * 1000
        audit.log("search_read", model, {"domain": domain, "count": len(result)}, duration)
        return _serialize(result)

    @mcp.tool()
    def odoo_count(model: str, domain: list | None = None) -> str:
        """Count records matching a domain.

        Args:
            model: Odoo model name
            domain: Search domain filter
        """
        t0 = time.time()
        try:
            perm = rbac.check_model_access(role, model, "search_read")
        except PermissionDenied as e:
            return f"Permission denied: {e}"

        domain = rbac.inject_domain(perm, domain or [], uid)

        try:
            count = client.execute_kw(model, "search_count", [domain])
        except OdooError as e:
            return f"Odoo error: {e}"

        duration = (time.time() - t0) * 1000
        audit.log("search_count", model, {"domain": domain, "count": count}, duration)
        return json.dumps({"count": count})

    @mcp.tool()
    def odoo_read(model: str, ids: list, fields: list | None = None) -> str:
        """Read specific records by ID.

        Args:
            model: Odoo model name
            ids: List of record IDs to read
            fields: Fields to return
        """
        t0 = time.time()
        try:
            perm = rbac.check_model_access(role, model, "search_read")
        except PermissionDenied as e:
            return f"Permission denied: {e}"

        # Ownership check: if role has domain_filter, verify the IDs belong to this user
        if perm.domain_filter:
            scoped_domain = rbac.inject_domain(perm, [("id", "in", ids)], uid)
            try:
                owned_ids = client.execute_kw(model, "search", [scoped_domain])
            except OdooError as e:
                return f"Odoo error: {e}"
            denied_ids = set(ids) - set(owned_ids)
            if denied_ids:
                return f"Permission denied: records {sorted(denied_ids)} are outside your scope"
            ids = owned_ids

        if fields:
            fields = rbac.filter_fields(perm, fields)

        try:
            result = client.execute_kw(
                model, "read", [ids], {"fields": fields or []}
            )
        except OdooError as e:
            return f"Odoo error: {e}"

        if perm.fields_denied and not fields:
            for record in result:
                for f in perm.fields_denied:
                    record.pop(f, None)

        duration = (time.time() - t0) * 1000
        audit.log("read", model, {"ids": ids}, duration)
        return _serialize(result)

    @mcp.tool()
    def odoo_fields(model: str, attributes: list | None = None) -> str:
        """Get field definitions for a model. Useful to discover available fields.

        Args:
            model: Odoo model name
            attributes: Field attributes to return (e.g. ['string', 'type', 'required'])
        """
        t0 = time.time()
        try:
            rbac.check_model_access(role, model, "search_read")
        except PermissionDenied as e:
            return f"Permission denied: {e}"

        try:
            result = client.execute_kw(
                model, "fields_get", [],
                {"attributes": attributes or ["string", "type", "required", "readonly"]}
            )
        except OdooError as e:
            return f"Odoo error: {e}"

        duration = (time.time() - t0) * 1000
        audit.log("fields_get", model, {}, duration)
        return _serialize(result)

    # ── Mutation tools (admin and developer) — two-phase: preview → confirm

    if role in ("administrativo", "developer"):

        @mcp.tool()
        def odoo_write(model: str, ids: list, values: dict, reason: str | None = None) -> str:
            """Update records. Returns a PREVIEW of changes — does NOT execute yet.
            You must show the preview to the user and call odoo_confirm after approval.
            For massive actions (>threshold records), ask the user for a reason before calling.

            Args:
                model: Odoo model name
                ids: List of record IDs to update
                values: Dictionary of field values to write
                reason: Why this change is needed (required for massive actions)
            """
            try:
                perm = rbac.check_model_access(role, model, "write")
            except PermissionDenied as e:
                return f"Permission denied: {e}"

            values = rbac.strip_protected_fields(values)
            for f in perm.fields_denied:
                values.pop(f, None)
            if not values:
                return "No writable fields in values after filtering"

            # Read current values for preview
            changed_fields = list(values.keys())
            # Include name/display_name for readability
            read_fields = list(set(changed_fields + ["name", "display_name"]))
            try:
                old_records = client.execute_kw(
                    model, "read", [ids], {"fields": read_fields}
                )
            except OdooError as e:
                return f"Odoo error reading current values: {e}"

            is_massive = len(ids) > massive_threshold
            preview = _build_write_preview(model, old_records, values)

            needs_approval = rbac.always_approve(role) or (is_massive and role != "developer")
            status = "approval_required" if needs_approval else "pending"

            pending_id = audit.create_pending(
                action="write", model=model, record_ids=ids,
                old_values=old_records, new_values=values,
                preview=preview, is_massive=is_massive,
                record_count=len(ids),
                details={"fields": changed_fields, "reason": reason},
                expiry_minutes=expiry_minutes,
                status=status,
            )

            if needs_approval:
                # Send approval request to configured channel
                msg_id, channel_type = notify_approval(
                    pending_id=pending_id, action="write", model=model,
                    record_count=len(ids), preview=preview, reason=reason,
                )
                if msg_id:
                    audit.update_pending_telegram_id(pending_id, msg_id)

                return _serialize({
                    "status": f"BLOQUEADO — solicitud enviada a {channel_type} para aprobacion",
                    "pending_id": pending_id,
                    "is_massive": True,
                    "record_count": len(ids),
                    "massive_threshold": massive_threshold,
                    "preview": preview,
                    "notified": msg_id is not None,
                    "notification_channel": channel_type,
                    "instructions": "Muestra el preview al usuario. La solicitud fue enviada "
                    f"al grupo de aprobaciones en {channel_type}. El usuario puede cerrar la sesion — "
                    "sera notificado cuando se apruebe o rechace.",
                })

            return _serialize({
                "status": "pendiente de confirmacion",
                "pending_id": pending_id,
                "is_massive": is_massive,
                "record_count": len(ids),
                "preview": preview,
                "instructions": "Muestra el preview al usuario. Si aprueba, llama odoo_confirm(pending_id). Si rechaza, llama odoo_cancel(pending_id).",
            })

        @mcp.tool()
        def odoo_create(model: str, values: dict) -> str:
            """Create a new record. Returns a PREVIEW — does NOT execute yet.
            You must show the preview to the user and call odoo_confirm after approval.

            Args:
                model: Odoo model name
                values: Dictionary of field values for the new record
            """
            try:
                perm = rbac.check_model_access(role, model, "create")
            except PermissionDenied as e:
                return f"Permission denied: {e}"

            values = rbac.strip_protected_fields(values)
            for f in perm.fields_denied:
                values.pop(f, None)

            preview = _build_create_preview(model, values)

            pending_id = audit.create_pending(
                action="create", model=model, record_ids=[],
                old_values=None, new_values=values,
                preview=preview, is_massive=False,
                record_count=1,
                expiry_minutes=expiry_minutes,
            )

            return _serialize({
                "status": "pendiente de confirmacion",
                "pending_id": pending_id,
                "preview": preview,
                "instructions": "Muestra el preview al usuario. Si aprueba, llama odoo_confirm(pending_id). Si rechaza, llama odoo_cancel(pending_id).",
            })

        @mcp.tool()
        def odoo_execute(model: str, method: str, args: list | None = None,
                         kwargs: dict | None = None, reason: str | None = None) -> str:
            """Execute a model method. Returns a PREVIEW — does NOT execute yet.
            You must show the preview to the user and call odoo_confirm after approval.

            Args:
                model: Odoo model name
                method: Method name to call
                args: Positional arguments
                kwargs: Keyword arguments
                reason: Why this action is needed (required for massive actions)
            """
            if not rbac.check_method_access(role, model, method):
                return f"Permission denied: method '{method}' on '{model}' not allowed for role '{role}'"

            record_ids = args[0] if args and isinstance(args[0], list) else []
            is_massive = len(record_ids) > massive_threshold
            preview = _build_execute_preview(model, method, record_ids)
            needs_approval = rbac.always_approve(role) or (is_massive and role != "developer")
            status = "approval_required" if needs_approval else "pending"

            pending_id = audit.create_pending(
                action="execute", model=model, record_ids=record_ids,
                old_values=None,
                new_values={"method": method, "args": args or [], "kwargs": kwargs},
                preview=preview, is_massive=is_massive,
                record_count=len(record_ids),
                details={"method": method, "reason": reason},
                expiry_minutes=expiry_minutes,
                status=status,
            )

            if needs_approval:
                msg_id, channel_type = notify_approval(
                    pending_id=pending_id, action=f"execute:{method}", model=model,
                    record_count=len(record_ids), preview=preview, reason=reason,
                )
                if msg_id:
                    audit.update_pending_telegram_id(pending_id, msg_id)

                return _serialize({
                    "status": f"BLOQUEADO — solicitud enviada a {channel_type} para aprobacion",
                    "pending_id": pending_id,
                    "is_massive": True,
                    "record_count": len(record_ids),
                    "massive_threshold": massive_threshold,
                    "preview": preview,
                    "notified": msg_id is not None,
                    "notification_channel": channel_type,
                    "instructions": "Muestra el preview al usuario. La solicitud fue enviada "
                    f"al grupo de aprobaciones en {channel_type}. El usuario puede cerrar la sesion — "
                    "sera notificado cuando se apruebe o rechace.",
                })

            return _serialize({
                "status": "pendiente de confirmacion",
                "pending_id": pending_id,
                "preview": preview,
                "instructions": "Muestra el preview al usuario. Si aprueba, llama odoo_confirm(pending_id). Si rechaza, llama odoo_cancel(pending_id).",
            })

        @mcp.tool()
        def odoo_confirm(pending_id: int) -> str:
            """Confirm and execute a pending action after user approval.
            NEVER call this without showing the preview to the user first.

            Args:
                pending_id: The pending action ID returned by odoo_write/create/execute/delete
            """
            pending = audit.get_pending(pending_id)
            if not pending:
                return f"Pending action {pending_id} not found"

            if pending["status"] == "approval_required":
                return _serialize({
                    "error": "BLOQUEADO — esta accion masiva requiere aprobacion externa",
                    "pending_id": pending_id,
                    "record_count": pending.get("record_count"),
                    "instructions": "Esta accion no se puede confirmar desde aqui. "
                    "Debe ser aprobada por un administrador via Slack/Telegram.",
                })

            if pending["status"] != "pending":
                return f"Action {pending_id} is not pending (status: {pending['status']})"

            if pending["user_login"] != username:
                return f"Permission denied: this action belongs to {pending['user_login']}"

            action = pending["action"]
            model = pending["model"]
            record_ids = pending.get("record_ids") or []
            new_values = pending.get("new_values")
            old_values = pending.get("old_values")

            t0 = time.time()
            try:
                if action == "write":
                    result = client.execute_kw(model, "write", [record_ids, new_values])
                    duration = (time.time() - t0) * 1000
                    audit_id = audit.log_mutation(
                        "write", model, record_ids,
                        old_values=old_values, new_values=new_values,
                        details=pending.get("details"), duration_ms=duration,
                    )
                    audit.confirm_pending(pending_id, audit_id)
                    return _serialize({
                        "success": result, "ids": record_ids,
                        "audit_id": audit_id, "pending_id": pending_id,
                    })

                elif action == "create":
                    new_id = client.execute_kw(model, "create", [new_values])
                    duration = (time.time() - t0) * 1000
                    audit_id = audit.log_mutation(
                        "create", model, [new_id],
                        old_values=None, new_values=new_values,
                        duration_ms=duration,
                    )
                    audit.confirm_pending(pending_id, audit_id)
                    return _serialize({
                        "id": new_id, "audit_id": audit_id,
                        "pending_id": pending_id,
                    })

                elif action == "execute":
                    method = new_values["method"]
                    args = new_values.get("args", [])
                    kwargs = new_values.get("kwargs")
                    result = client.execute_kw(model, method, args, kwargs)
                    duration = (time.time() - t0) * 1000
                    audit_id = audit.log_mutation(
                        "execute", model, record_ids,
                        old_values=None, new_values=new_values,
                        details={"method": method}, duration_ms=duration,
                    )
                    audit.confirm_pending(pending_id, audit_id)
                    return _serialize(result) if result else '{"success": true}'

                elif action == "unlink":
                    result = client.execute_kw(model, "unlink", [record_ids])
                    duration = (time.time() - t0) * 1000
                    audit_id = audit.log_mutation(
                        "unlink", model, record_ids,
                        old_values=old_values, new_values=None,
                        duration_ms=duration,
                    )
                    audit.confirm_pending(pending_id, audit_id)
                    return _serialize({
                        "success": result, "deleted_ids": record_ids,
                        "audit_id": audit_id,
                    })

                else:
                    return f"Unknown action type: {action}"

            except OdooError as e:
                return f"Odoo error: {e}"

        @mcp.tool()
        def odoo_cancel(pending_id: int) -> str:
            """Cancel a pending action. Use when the user rejects the preview.

            Args:
                pending_id: The pending action ID to cancel
            """
            pending = audit.get_pending(pending_id)
            if not pending:
                return f"Pending action {pending_id} not found"
            if pending["user_login"] != username:
                return f"Permission denied: this action belongs to {pending['user_login']}"
            if pending["status"] != "pending":
                return f"Action {pending_id} is not pending (status: {pending['status']})"

            audit.cancel_pending(pending_id)
            return _serialize({"cancelled": True, "pending_id": pending_id})

    # ── Delete tool (developer only) ────────────────────────────────────

    if role == "developer":

        @mcp.tool()
        def odoo_delete(model: str, ids: list, reason: str | None = None) -> str:
            """Delete records. Returns a PREVIEW — does NOT execute yet.
            You must show the preview to the user and call odoo_confirm after approval.

            Args:
                model: Odoo model name
                ids: List of record IDs to delete
                reason: Why this deletion is needed (required for massive actions)
            """
            try:
                rbac.check_model_access(role, model, "unlink")
            except PermissionDenied as e:
                return f"Permission denied: {e}"

            try:
                old_records = client.execute_kw(model, "read", [ids])
            except OdooError as e:
                return f"Odoo error reading records: {e}"

            is_massive = len(ids) > massive_threshold
            preview = _build_delete_preview(model, old_records)
            needs_approval = rbac.always_approve(role) or (is_massive and role != "developer")
            status = "approval_required" if needs_approval else "pending"

            pending_id = audit.create_pending(
                action="unlink", model=model, record_ids=ids,
                old_values=old_records, new_values=None,
                preview=preview, is_massive=is_massive,
                record_count=len(ids),
                details={"reason": reason},
                expiry_minutes=expiry_minutes,
                status=status,
            )

            if needs_approval:
                msg_id, channel_type = notify_approval(
                    pending_id=pending_id, action="delete", model=model,
                    record_count=len(ids), preview=preview, reason=reason,
                )
                if msg_id:
                    audit.update_pending_telegram_id(pending_id, msg_id)

                return _serialize({
                    "status": f"BLOQUEADO — solicitud enviada a {channel_type} para aprobacion",
                    "pending_id": pending_id,
                    "is_massive": True,
                    "record_count": len(ids),
                    "massive_threshold": massive_threshold,
                    "preview": preview,
                    "notified": msg_id is not None,
                    "notification_channel": channel_type,
                    "instructions": "Muestra el preview al usuario. La solicitud fue enviada "
                    f"al grupo de aprobaciones en {channel_type}. El usuario puede cerrar la sesion — "
                    "sera notificado cuando se apruebe o rechace.",
                })

            return _serialize({
                "status": "pendiente de confirmacion",
                "pending_id": pending_id,
                "record_count": len(ids),
                "preview": preview,
                "instructions": "Muestra el preview al usuario. Si aprueba, llama odoo_confirm(pending_id). Si rechaza, llama odoo_cancel(pending_id).",
            })

    # ── Audit query tool (all roles — scoped by role) ─────────────────

    @mcp.tool()
    def odoo_audit_log(model: str | None = None, action: str | None = None,
                       user_login: str | None = None,
                       audit_id: int | None = None, limit: int = 20) -> str:
        """Query the MCP audit log. Shows mutations with before/after values.
        Vendedor/administrativo see only their own logs. Developer sees all.

        Args:
            model: Filter by model name
            action: Filter by action (write, create, unlink, execute)
            user_login: Filter by user (developer only, others are auto-scoped)
            audit_id: Get a specific audit entry by ID
            limit: Max entries to return (default 20)
        """
        if audit_id:
            entry = audit.get_log(audit_id)
            if not entry:
                return f"Audit entry {audit_id} not found"
            if role != "developer" and entry.get("user_login") != username:
                return "Permission denied: you can only view your own audit entries"
            return _serialize(entry)

        if role != "developer":
            user_login = username
        return _serialize(audit.query_logs(
            model=model, action=action, user=user_login, limit=limit,
        ))

    return mcp
