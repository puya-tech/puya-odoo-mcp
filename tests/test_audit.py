import json
from unittest.mock import MagicMock, patch

from puya_odoo_mcp.audit import AuditLogger


def _mock_response(data):
    """Create a mock urlopen response."""
    resp = MagicMock()
    resp.read.return_value = json.dumps(data).encode()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestAuditLoggerDisabled:
    """When Supabase is not configured, mutations log to stdout only."""

    def test_log_mutation_returns_none(self):
        audit = AuditLogger(user="test@example.com", role="developer")
        result = audit.log_mutation("write", "res.partner", [1], None, {"name": "X"})
        assert result is None

    def test_query_returns_empty(self):
        audit = AuditLogger(user="test@example.com", role="developer")
        assert audit.query_logs() == []

    def test_get_log_returns_none(self):
        audit = AuditLogger(user="test@example.com", role="developer")
        assert audit.get_log(1) is None


class TestAuditLoggerWithSupabase:

    def setup_method(self):
        self.audit = AuditLogger(
            user="test@example.com", role="developer",
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
        )

    @patch("puya_odoo_mcp.audit.urlopen")
    def test_log_mutation_write(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response([{"id": 42}])

        old = [{"id": 1, "name": "Before"}]
        new = {"name": "After"}
        audit_id = self.audit.log_mutation(
            "write", "res.partner", [1],
            old_values=old, new_values=new,
            duration_ms=15.3,
        )
        assert audit_id == 42

        # Verify the POST was called
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.method == "POST"
        assert "mcp_audit_log" in req.full_url
        body = json.loads(req.data)
        assert body["action"] == "write"
        assert body["model"] == "res.partner"
        assert body["old_values"] == old
        assert body["new_values"] == new

    @patch("puya_odoo_mcp.audit.urlopen")
    def test_log_mutation_create(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response([{"id": 99}])

        audit_id = self.audit.log_mutation(
            "create", "sale.order", [5],
            old_values=None, new_values={"partner_id": 1},
        )
        assert audit_id == 99

    @patch("puya_odoo_mcp.audit.urlopen")
    def test_get_log(self, mock_urlopen):
        entry = {"id": 42, "action": "write", "model": "res.partner",
                 "user_login": "test@example.com"}
        mock_urlopen.return_value = _mock_response([entry])

        result = self.audit.get_log(42)
        assert result["id"] == 42
        assert result["action"] == "write"

        req = mock_urlopen.call_args[0][0]
        assert "id=eq.42" in req.full_url

    @patch("puya_odoo_mcp.audit.urlopen")
    def test_query_logs_with_filters(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response([
            {"id": 1, "model": "res.partner", "action": "write"},
        ])

        result = self.audit.query_logs(model="res.partner", action="write", limit=10)
        assert len(result) == 1

        req = mock_urlopen.call_args[0][0]
        assert "model=eq.res.partner" in req.full_url
        assert "action=eq.write" in req.full_url
        assert "limit=10" in req.full_url

    @patch("puya_odoo_mcp.audit.urlopen")
    def test_query_logs_by_user(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response([])
        self.audit.query_logs(user="vendedor@example.com")

        req = mock_urlopen.call_args[0][0]
        assert "user_login=eq.vendedor@example.com" in req.full_url

    @patch("puya_odoo_mcp.audit.urlopen")
    def test_mark_reverted(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response([{"id": 42, "reverted": True}])

        result = self.audit.mark_reverted(42, reverted_by="admin@example.com")
        assert result is True

        req = mock_urlopen.call_args[0][0]
        assert req.method == "PATCH"
        body = json.loads(req.data)
        assert body["reverted"] is True
        assert body["reverted_by"] == "admin@example.com"

    @patch("puya_odoo_mcp.audit.urlopen")
    def test_handles_http_error(self, mock_urlopen):
        from urllib.error import HTTPError
        mock_urlopen.side_effect = HTTPError(
            "https://test.supabase.co", 500, "Internal Server Error", {}, None
        )

        # Should not raise, returns None
        result = self.audit.log_mutation("write", "res.partner", [1], None, {"name": "X"})
        assert result is None


class TestAuditHeaders:
    def test_headers_include_auth(self):
        audit = AuditLogger(
            user="x", role="y",
            supabase_url="https://test.supabase.co",
            supabase_key="my-key",
        )
        h = audit._headers()
        assert h["apikey"] == "my-key"
        assert h["Authorization"] == "Bearer my-key"
        assert h["Prefer"] == "return=representation"
