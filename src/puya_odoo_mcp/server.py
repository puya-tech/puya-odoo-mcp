import json
import logging
import time

from mcp.server.fastmcp import FastMCP

from .audit import AuditLogger
from .config import Config
from .odoo_client import OdooClient, OdooError
from .rbac import PermissionDenied, RBACEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("puya_odoo_mcp")


def create_server() -> FastMCP:
    config = Config()
    client = OdooClient(config.odoo_url, config.odoo_db, config.odoo_api_key)
    uid = client.authenticate()
    role = client.get_user_role()

    user_info = client.execute_kw("res.users", "read", [[uid]], {"fields": ["login"]})
    username = user_info[0]["login"] if user_info else str(uid)

    logger.info(f"Authenticated as {username} (uid={uid}, role={role})")

    rbac = RBACEngine()
    audit = AuditLogger(user=username, role=role)

    mcp = FastMCP(
        "Odoo",
        instructions=f"Odoo 16 MCP server. User: {username}, Role: {role}. "
        "Use odoo_search to query data, odoo_fields to inspect models.",
    )

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
        elif perm.fields_denied:
            # If no fields specified but some are denied, we need to exclude them
            # by fetching all fields first, then filtering
            pass  # Let Odoo return all, we'll filter after

        limit = min(limit, 200)
        kwargs = {"fields": fields or [], "limit": limit, "offset": offset}
        if order:
            kwargs["order"] = order

        try:
            result = client.execute_kw(model, "search_read", [domain], kwargs)
        except OdooError as e:
            return f"Odoo error: {e}"

        # Filter denied fields from result
        if perm.fields_denied and not fields:
            for record in result:
                for f in perm.fields_denied:
                    record.pop(f, None)

        duration = (time.time() - t0) * 1000
        audit.log("search_read", model, {"domain": domain, "count": len(result)}, duration)
        return json.dumps(result, default=str, ensure_ascii=False)

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
        return json.dumps(result, default=str, ensure_ascii=False)

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
        return json.dumps(result, default=str, ensure_ascii=False)

    # Write/create tools — only for admin and developer
    if role in ("administrativo", "developer"):

        @mcp.tool()
        def odoo_write(model: str, ids: list, values: dict) -> str:
            """Update existing records.

            Args:
                model: Odoo model name
                ids: List of record IDs to update
                values: Dictionary of field values to write
            """
            t0 = time.time()
            try:
                perm = rbac.check_model_access(role, model, "write")
            except PermissionDenied as e:
                return f"Permission denied: {e}"

            # Remove denied fields from values
            for f in perm.fields_denied:
                values.pop(f, None)

            try:
                result = client.execute_kw(model, "write", [ids, values])
            except OdooError as e:
                return f"Odoo error: {e}"

            duration = (time.time() - t0) * 1000
            audit.log("write", model, {"ids": ids, "fields": list(values.keys())}, duration)
            return json.dumps({"success": result, "ids": ids})

        @mcp.tool()
        def odoo_create(model: str, values: dict) -> str:
            """Create a new record.

            Args:
                model: Odoo model name
                values: Dictionary of field values for the new record
            """
            t0 = time.time()
            try:
                perm = rbac.check_model_access(role, model, "create")
            except PermissionDenied as e:
                return f"Permission denied: {e}"

            for f in perm.fields_denied:
                values.pop(f, None)

            try:
                new_id = client.execute_kw(model, "create", [values])
            except OdooError as e:
                return f"Odoo error: {e}"

            duration = (time.time() - t0) * 1000
            audit.log("create", model, {"new_id": new_id}, duration)
            return json.dumps({"id": new_id})

        @mcp.tool()
        def odoo_execute(model: str, method: str, args: list | None = None,
                         kwargs: dict | None = None) -> str:
            """Execute a model method (e.g. action_confirm on sale.order).

            Args:
                model: Odoo model name
                method: Method name to call
                args: Positional arguments
                kwargs: Keyword arguments
            """
            t0 = time.time()
            if not rbac.check_method_access(role, model, method):
                return f"Permission denied: method '{method}' on '{model}' not allowed for role '{role}'"

            try:
                result = client.execute_kw(model, method, args or [], kwargs)
            except OdooError as e:
                return f"Odoo error: {e}"

            duration = (time.time() - t0) * 1000
            audit.log("execute", model, {"method": method}, duration)
            return json.dumps(result, default=str, ensure_ascii=False) if result else '{"success": true}'

    # Unlink — only for developer
    if role == "developer":

        @mcp.tool()
        def odoo_delete(model: str, ids: list) -> str:
            """Delete records. Developer only.

            Args:
                model: Odoo model name
                ids: List of record IDs to delete
            """
            t0 = time.time()
            try:
                rbac.check_model_access(role, model, "unlink")
            except PermissionDenied as e:
                return f"Permission denied: {e}"

            try:
                result = client.execute_kw(model, "unlink", [ids])
            except OdooError as e:
                return f"Odoo error: {e}"

            duration = (time.time() - t0) * 1000
            audit.log("unlink", model, {"ids": ids}, duration)
            return json.dumps({"success": result, "deleted_ids": ids})

    return mcp
