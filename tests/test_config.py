import os
import pytest

from puya_odoo_mcp.config import Config, ConfigError


def test_valid_config(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://test.odoo.com")
    monkeypatch.setenv("ODOO_DB", "testdb")
    monkeypatch.setenv("ODOO_API_KEY", "key123")
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"
    assert config.odoo_db == "testdb"
    assert config.odoo_api_key == "key123"


def test_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://test.odoo.com/")
    monkeypatch.setenv("ODOO_DB", "testdb")
    monkeypatch.setenv("ODOO_API_KEY", "key123")
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"


def test_missing_vars(monkeypatch):
    monkeypatch.delenv("ODOO_URL", raising=False)
    monkeypatch.delenv("ODOO_DB", raising=False)
    monkeypatch.delenv("ODOO_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="ODOO_URL"):
        Config()
