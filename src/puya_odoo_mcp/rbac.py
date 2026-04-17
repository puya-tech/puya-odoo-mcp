import ast
from pathlib import Path

import yaml


class PermissionDenied(Exception):
    pass


class Permission:
    def __init__(self, operations: list, fields_denied: list | None = None,
                 domain_filter: str | None = None):
        self.operations = operations
        self.fields_denied = fields_denied or []
        self.domain_filter = domain_filter


# Models blocked for non-developer roles because reading them exposes secrets.
# Other system models (ir.cron, ir.rule, res.groups, etc.) are readable
# because seeing config is harmless — writing is already blocked by RBAC.
INFRA_BLOCKED_MODELS = frozenset([
    # Contains system secrets (email keys, integration tokens, etc.)
    "ir.config_parameter",
    # User credentials and authentication
    "res.users.apikeys",
    "res.users.apikeys.show",
    "res.users.apikeys.description",
    "change.password.wizard",
    "change.password.user",
    "change.password.own",
    # Payment tokens
    "payment.token",
])

# Fields that must never be writable via MCP, even for developer.
# These are the fields that control MCP access itself.
PROTECTED_FIELDS = frozenset([
    "x_mcp_role",
])


class RBACEngine:
    def __init__(self, permissions_path: str | Path | None = None):
        if permissions_path is None:
            # Look inside the package first (pip install), fall back to repo root (dev)
            pkg_path = Path(__file__).parent / "permissions.yaml"
            repo_path = Path(__file__).parent.parent.parent / "permissions.yaml"
            permissions_path = pkg_path if pkg_path.exists() else repo_path
        with open(permissions_path) as f:
            data = yaml.safe_load(f)
        self._roles = data.get("roles", {})
        self._settings = data.get("settings", {})

    @property
    def massive_threshold(self) -> int:
        return self._settings.get("massive_threshold", 10)

    @property
    def pending_expiry_minutes(self) -> int:
        return self._settings.get("pending_expiry_minutes", 10)

    def _get_role_config(self, role: str) -> dict:
        config = self._roles.get(role)
        if config is None:
            raise PermissionDenied(f"Unknown role: {role}")
        return config

    def check_model_access(self, role: str, model: str, operation: str) -> Permission:
        config = self._get_role_config(role)

        # Infra models blocked for all non-developer roles
        if role != "developer" and model in INFRA_BLOCKED_MODELS:
            raise PermissionDenied(f"Model '{model}' is blocked for role '{role}'")

        # Per-role blocked models
        blocked = config.get("blocked_models", [])
        if model in blocked:
            raise PermissionDenied(f"Model '{model}' is blocked for role '{role}'")

        models_config = config.get("models", {})

        # Check exact model match first, then wildcard
        model_config = models_config.get(model)
        if model_config is None:
            model_config = models_config.get("*")
        if model_config is None:
            raise PermissionDenied(
                f"Role '{role}' has no access to model '{model}'"
            )

        allowed_ops = model_config.get("operations", [])
        if operation not in allowed_ops:
            raise PermissionDenied(
                f"Operation '{operation}' not allowed on '{model}' for role '{role}'"
            )

        return Permission(
            operations=allowed_ops,
            fields_denied=model_config.get("fields_denied", []),
            domain_filter=model_config.get("domain_filter"),
        )

    def filter_fields(self, permission: Permission, fields: list) -> list:
        if not permission.fields_denied:
            return fields
        return [f for f in fields if f not in permission.fields_denied]

    def strip_protected_fields(self, values: dict) -> dict:
        """Remove fields that must never be written via MCP."""
        return {k: v for k, v in values.items() if k not in PROTECTED_FIELDS}

    def inject_domain(self, permission: Permission, domain: list, uid: int) -> list:
        if not permission.domain_filter:
            return domain
        extra = ast.literal_eval(permission.domain_filter.replace("{uid}", str(uid)))
        return (domain or []) + extra

    def check_method_access(self, role: str, model: str, method: str) -> bool:
        config = self._get_role_config(role)

        blocked = config.get("blocked_models", [])
        if model in blocked:
            return False

        # Infra models blocked for non-developer
        if role != "developer" and model in INFRA_BLOCKED_MODELS:
            return False

        allowed = config.get("methods_allowed", [])
        if "*" in allowed:
            return True
        return f"{model}:{method}" in allowed

    def get_rate_limit(self, role: str) -> int:
        config = self._get_role_config(role)
        return config.get("rate_limit", 60)

    def always_approve(self, role: str) -> bool:
        """Check if this role requires approval for ALL mutations."""
        config = self._get_role_config(role)
        return config.get("always_approve", False)
