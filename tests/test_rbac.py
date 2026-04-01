import pytest
from pathlib import Path

from puya_odoo_mcp.rbac import RBACEngine, PermissionDenied, INFRA_BLOCKED_MODELS, PROTECTED_FIELDS

PERMISSIONS_PATH = Path(__file__).parent.parent / "permissions.yaml"


@pytest.fixture
def rbac():
    return RBACEngine(PERMISSIONS_PATH)


class TestVendedor:
    def test_can_search_partners(self, rbac):
        perm = rbac.check_model_access("vendedor", "res.partner", "search_read")
        assert "search_read" in perm.operations

    def test_cannot_write_partners(self, rbac):
        with pytest.raises(PermissionDenied):
            rbac.check_model_access("vendedor", "res.partner", "write")

    def test_can_search_any_model(self, rbac):
        """Vendedor can read any non-blocked model (open exploration)."""
        perm = rbac.check_model_access("vendedor", "hr.employee", "search_read")
        assert "search_read" in perm.operations

    def test_no_domain_filter_on_wildcard(self, rbac):
        """Open read — no domain filters restricting to own records."""
        perm = rbac.check_model_access("vendedor", "sale.order", "search_read")
        assert perm.domain_filter is None

    def test_blocked_model(self, rbac):
        with pytest.raises(PermissionDenied):
            rbac.check_model_access("vendedor", "ir.config_parameter", "search_read")

    def test_no_method_access(self, rbac):
        assert not rbac.check_method_access("vendedor", "sale.order", "action_confirm")

    def test_cannot_write_any_model(self, rbac):
        with pytest.raises(PermissionDenied):
            rbac.check_model_access("vendedor", "sale.order", "write")


class TestAdministrativo:
    def test_can_write_partners(self, rbac):
        perm = rbac.check_model_access("administrativo", "res.partner", "write")
        assert "write" in perm.operations

    def test_can_search_any_model(self, rbac):
        """Administrativo can read any non-blocked model."""
        perm = rbac.check_model_access("administrativo", "hr.employee", "search_read")
        assert "search_read" in perm.operations

    def test_cannot_write_unknown_model(self, rbac):
        """Can read any model but cannot write to models not explicitly listed."""
        with pytest.raises(PermissionDenied):
            rbac.check_model_access("administrativo", "hr.employee", "write")

    def test_can_confirm_sale(self, rbac):
        assert rbac.check_method_access("administrativo", "sale.order", "action_confirm")

    def test_cannot_confirm_arbitrary(self, rbac):
        assert not rbac.check_method_access("administrativo", "sale.order", "unlink")

    def test_blocked_model(self, rbac):
        with pytest.raises(PermissionDenied):
            rbac.check_model_access("administrativo", "res.users", "search_read")


class TestDeveloper:
    def test_wildcard_access(self, rbac):
        perm = rbac.check_model_access("developer", "any.model", "search_read")
        assert "search_read" in perm.operations

    def test_all_methods_allowed(self, rbac):
        assert rbac.check_method_access("developer", "any.model", "any_method")

    def test_can_unlink(self, rbac):
        perm = rbac.check_model_access("developer", "res.partner", "unlink")
        assert "unlink" in perm.operations


class TestInfraBlockedModels:
    """Infra/secret models must be blocked for all non-developer roles."""

    @pytest.mark.parametrize("model", sorted(INFRA_BLOCKED_MODELS))
    def test_vendedor_blocked(self, rbac, model):
        with pytest.raises(PermissionDenied):
            rbac.check_model_access("vendedor", model, "search_read")

    @pytest.mark.parametrize("model", sorted(INFRA_BLOCKED_MODELS))
    def test_administrativo_blocked(self, rbac, model):
        with pytest.raises(PermissionDenied):
            rbac.check_model_access("administrativo", model, "search_read")

    @pytest.mark.parametrize("model", sorted(INFRA_BLOCKED_MODELS))
    def test_administrativo_method_blocked(self, rbac, model):
        assert not rbac.check_method_access("administrativo", model, "any_method")

    def test_developer_can_access_infra(self, rbac):
        """Developer is the exception — can access infra models."""
        perm = rbac.check_model_access("developer", "res.users", "search_read")
        assert "search_read" in perm.operations

    def test_apikeys_blocked(self, rbac):
        """API key models must be blocked."""
        for model in ["res.users.apikeys", "res.users.apikeys.show"]:
            with pytest.raises(PermissionDenied):
                rbac.check_model_access("vendedor", model, "search_read")

    def test_password_models_blocked(self, rbac):
        """Password change models must be blocked."""
        for model in ["change.password.wizard", "change.password.user", "change.password.own"]:
            with pytest.raises(PermissionDenied):
                rbac.check_model_access("administrativo", model, "search_read")


class TestProtectedFields:
    def test_strip_protected_fields(self, rbac):
        values = {"name": "Test", "x_mcp_role": "developer", "email": "a@b.com"}
        cleaned = rbac.strip_protected_fields(values)
        assert "x_mcp_role" not in cleaned
        assert cleaned == {"name": "Test", "email": "a@b.com"}

    def test_strip_empty_after_protection(self, rbac):
        values = {"x_mcp_role": "developer"}
        cleaned = rbac.strip_protected_fields(values)
        assert cleaned == {}


class TestFilterFields:
    def test_no_fields_denied_on_wildcard(self, rbac):
        """Wildcard read has no field restrictions."""
        perm = rbac.check_model_access("vendedor", "product.product", "search_read")
        assert perm.fields_denied == []

    def test_filter_fields_passthrough(self, rbac):
        """With no denied fields, all fields pass through."""
        perm = rbac.check_model_access("vendedor", "res.partner", "search_read")
        fields = ["name", "email", "credit_limit"]
        filtered = rbac.filter_fields(perm, fields)
        assert filtered == fields


class TestRateLimit:
    def test_vendedor_rate(self, rbac):
        assert rbac.get_rate_limit("vendedor") == 60

    def test_developer_rate(self, rbac):
        assert rbac.get_rate_limit("developer") == 300

    def test_unknown_role(self, rbac):
        with pytest.raises(PermissionDenied):
            rbac.get_rate_limit("hacker")
