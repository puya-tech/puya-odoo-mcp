import pytest
from pathlib import Path

from puya_odoo_mcp.rbac import RBACEngine, PermissionDenied

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

    def test_fields_denied(self, rbac):
        perm = rbac.check_model_access("vendedor", "res.partner", "search_read")
        assert "credit_limit" in perm.fields_denied

    def test_domain_filter(self, rbac):
        perm = rbac.check_model_access("vendedor", "res.partner", "search_read")
        assert perm.domain_filter is not None
        domain = rbac.inject_domain(perm, [], 42)
        assert ("user_id", "=", 42) in domain

    def test_blocked_model(self, rbac):
        with pytest.raises(PermissionDenied):
            rbac.check_model_access("vendedor", "ir.config_parameter", "search_read")

    def test_no_method_access(self, rbac):
        assert not rbac.check_method_access("vendedor", "sale.order", "action_confirm")

    def test_cannot_access_unknown_model(self, rbac):
        with pytest.raises(PermissionDenied):
            rbac.check_model_access("vendedor", "hr.employee", "search_read")


class TestAdministrativo:
    def test_can_write_partners(self, rbac):
        perm = rbac.check_model_access("administrativo", "res.partner", "write")
        assert "write" in perm.operations

    def test_can_confirm_sale(self, rbac):
        assert rbac.check_method_access("administrativo", "sale.order", "action_confirm")

    def test_cannot_confirm_arbitrary(self, rbac):
        assert not rbac.check_method_access("administrativo", "sale.order", "unlink")

    def test_blocked_model(self, rbac):
        with pytest.raises(PermissionDenied):
            rbac.check_model_access("administrativo", "res.users", "search_read")

    def test_standard_price_denied(self, rbac):
        perm = rbac.check_model_access("administrativo", "product.product", "search_read")
        assert "standard_price" in perm.fields_denied


class TestDeveloper:
    def test_wildcard_access(self, rbac):
        perm = rbac.check_model_access("developer", "any.model", "search_read")
        assert "search_read" in perm.operations

    def test_all_methods_allowed(self, rbac):
        assert rbac.check_method_access("developer", "any.model", "any_method")

    def test_can_unlink(self, rbac):
        perm = rbac.check_model_access("developer", "res.partner", "unlink")
        assert "unlink" in perm.operations


class TestFilterFields:
    def test_removes_denied(self, rbac):
        perm = rbac.check_model_access("vendedor", "product.product", "search_read")
        filtered = rbac.filter_fields(perm, ["name", "standard_price", "list_price"])
        assert "standard_price" not in filtered
        assert "name" in filtered
        assert "list_price" in filtered

    def test_no_denied_fields(self, rbac):
        perm = rbac.check_model_access("administrativo", "res.partner", "search_read")
        fields = ["name", "email"]
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
