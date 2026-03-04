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


class RBACEngine:
    def __init__(self, permissions_path: str | Path | None = None):
        if permissions_path is None:
            permissions_path = Path(__file__).parent.parent.parent / "permissions.yaml"
        with open(permissions_path) as f:
            data = yaml.safe_load(f)
        self._roles = data.get("roles", {})

    def _get_role_config(self, role: str) -> dict:
        config = self._roles.get(role)
        if config is None:
            raise PermissionDenied(f"Unknown role: {role}")
        return config

    def check_model_access(self, role: str, model: str, operation: str) -> Permission:
        config = self._get_role_config(role)

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

    def inject_domain(self, permission: Permission, domain: list, uid: int) -> list:
        if not permission.domain_filter:
            return domain
        extra = eval(permission.domain_filter.replace("{uid}", str(uid)))
        return (domain or []) + extra

    def check_method_access(self, role: str, model: str, method: str) -> bool:
        config = self._get_role_config(role)

        blocked = config.get("blocked_models", [])
        if model in blocked:
            return False

        allowed = config.get("methods_allowed", [])
        if "*" in allowed:
            return True
        return f"{model}:{method}" in allowed

    def get_rate_limit(self, role: str) -> int:
        config = self._get_role_config(role)
        return config.get("rate_limit", 60)
