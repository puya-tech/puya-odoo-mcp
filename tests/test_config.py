import pytest

from puya_odoo_mcp.config import Config, ConfigError, CREDENTIALS_FILE


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Clear env vars so tests only use what they explicitly set."""
    monkeypatch.delenv("ODOO_URL", raising=False)
    monkeypatch.delenv("ODOO_DB", raising=False)
    monkeypatch.delenv("ODOO_API_KEY", raising=False)


def test_valid_config_from_env(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://test.odoo.com")
    monkeypatch.setenv("ODOO_DB", "testdb")
    monkeypatch.setenv("ODOO_API_KEY", "key123")
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"
    assert config.odoo_db == "testdb"
    assert config.odoo_api_key == "key123"


def test_valid_config_from_file(monkeypatch, tmp_path):
    creds_file = tmp_path / "credentials"
    creds_file.write_text(
        "ODOO_URL=https://file.odoo.com\n"
        "ODOO_DB=filedb\n"
        "ODOO_API_KEY=filekey\n"
    )
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds_file)
    config = Config()
    assert config.odoo_url == "https://file.odoo.com"
    assert config.odoo_api_key == "filekey"


def test_file_takes_priority_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ODOO_URL", "https://env.odoo.com")
    monkeypatch.setenv("ODOO_DB", "envdb")
    monkeypatch.setenv("ODOO_API_KEY", "envkey")
    creds_file = tmp_path / "credentials"
    creds_file.write_text(
        "ODOO_URL=https://file.odoo.com\n"
        "ODOO_DB=filedb\n"
        "ODOO_API_KEY=filekey\n"
    )
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds_file)
    config = Config()
    assert config.odoo_url == "https://file.odoo.com"
    assert config.odoo_api_key == "filekey"


def test_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://test.odoo.com/")
    monkeypatch.setenv("ODOO_DB", "testdb")
    monkeypatch.setenv("ODOO_API_KEY", "key123")
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"


def test_missing_config(monkeypatch, tmp_path):
    creds_file = tmp_path / "credentials"
    # File doesn't exist, env vars cleared by autouse fixture
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds_file)
    with pytest.raises(ConfigError, match="ODOO_URL"):
        Config()


def test_comments_and_blanks_in_file(monkeypatch, tmp_path):
    creds_file = tmp_path / "credentials"
    creds_file.write_text(
        "# This is a comment\n"
        "\n"
        "ODOO_URL=https://test.odoo.com\n"
        "ODOO_DB=testdb\n"
        "ODOO_API_KEY=key123\n"
    )
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds_file)
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"
