import pytest

from puya_odoo_mcp.config import Config, ConfigError, CREDENTIALS_FILE

FULL_CREDS = (
    "ODOO_URL=https://test.odoo.com\n"
    "ODOO_DB=testdb\n"
    "ODOO_LOGIN=user@test.com\n"
    "ODOO_API_KEY=key123\n"
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """Clear env vars and point credentials file to nonexistent path."""
    monkeypatch.delenv("ODOO_URL", raising=False)
    monkeypatch.delenv("ODOO_DB", raising=False)
    monkeypatch.delenv("ODOO_LOGIN", raising=False)
    monkeypatch.delenv("ODOO_API_KEY", raising=False)
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", tmp_path / "nocreds")


def test_valid_config_from_env(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://test.odoo.com")
    monkeypatch.setenv("ODOO_DB", "testdb")
    monkeypatch.setenv("ODOO_LOGIN", "user@test.com")
    monkeypatch.setenv("ODOO_API_KEY", "key123")
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"
    assert config.odoo_db == "testdb"
    assert config.odoo_login == "user@test.com"
    assert config.odoo_api_key == "key123"


def test_valid_config_from_file(monkeypatch, tmp_path):
    creds_file = tmp_path / "credentials"
    creds_file.write_text(FULL_CREDS)
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds_file)
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"
    assert config.odoo_login == "user@test.com"
    assert config.odoo_api_key == "key123"


def test_file_takes_priority_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ODOO_URL", "https://env.odoo.com")
    monkeypatch.setenv("ODOO_DB", "envdb")
    monkeypatch.setenv("ODOO_LOGIN", "env@test.com")
    monkeypatch.setenv("ODOO_API_KEY", "envkey")
    creds_file = tmp_path / "credentials"
    creds_file.write_text(FULL_CREDS)
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds_file)
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"
    assert config.odoo_api_key == "key123"


def test_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://test.odoo.com/")
    monkeypatch.setenv("ODOO_DB", "testdb")
    monkeypatch.setenv("ODOO_LOGIN", "user@test.com")
    monkeypatch.setenv("ODOO_API_KEY", "key123")
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"


def test_missing_config(monkeypatch, tmp_path):
    creds_file = tmp_path / "credentials"
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds_file)
    with pytest.raises(ConfigError, match="ODOO_URL"):
        Config()


def test_comments_and_blanks_in_file(monkeypatch, tmp_path):
    creds_file = tmp_path / "credentials"
    creds_file.write_text("# Comment\n\n" + FULL_CREDS)
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds_file)
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"
