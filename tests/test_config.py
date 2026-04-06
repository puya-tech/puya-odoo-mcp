import pytest

from puya_odoo_mcp.config import Config, ConfigError

FULL_CREDS = (
    "ODOO_URL=https://test.odoo.com\n"
    "ODOO_DB=testdb\n"
    "ODOO_LOGIN=user@test.com\n"
    "ODOO_API_KEY=key123\n"
)

SHARED_ONLY = (
    "ODOO_URL=https://shared.odoo.com\n"
    "ODOO_DB=shareddb\n"
    "SUPABASE_URL=https://shared.supabase.co\n"
    "TELEGRAM_CHAT_ID=-123\n"
)

USER_SECRETS = (
    "ODOO_LOGIN=user@test.com\n"
    "ODOO_API_KEY=key123\n"
    "SUPABASE_SERVICE_KEY=supa-secret\n"
    "TELEGRAM_BOT_TOKEN=bot-token\n"
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """Clear env vars and point files to temp paths."""
    for var in ["ODOO_URL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY", "ODOO_ENV",
                "SUPABASE_URL", "SUPABASE_SERVICE_KEY",
                "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", tmp_path / "nocreds")
    monkeypatch.setattr("puya_odoo_mcp.config.CONFIG_DIR", tmp_path / "noconfig")


def test_valid_config_from_env(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://test.odoo.com")
    monkeypatch.setenv("ODOO_DB", "testdb")
    monkeypatch.setenv("ODOO_LOGIN", "user@test.com")
    monkeypatch.setenv("ODOO_API_KEY", "key123")
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"
    assert config.odoo_db == "testdb"


def test_valid_config_from_file(monkeypatch, tmp_path):
    creds_file = tmp_path / "credentials"
    creds_file.write_text(FULL_CREDS)
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds_file)
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"
    assert config.odoo_login == "user@test.com"


def test_shared_plus_user_creds(monkeypatch, tmp_path):
    """shared.env provides URL/DB, user credentials provide login/key."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "shared.env").write_text(SHARED_ONLY)
    monkeypatch.setattr("puya_odoo_mcp.config.CONFIG_DIR", config_dir)

    creds = tmp_path / "credentials"
    creds.write_text(USER_SECRETS)
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds)

    config = Config()
    assert config.odoo_url == "https://shared.odoo.com"
    assert config.odoo_db == "shareddb"
    assert config.odoo_login == "user@test.com"
    assert config.odoo_api_key == "key123"
    assert config.supabase_url == "https://shared.supabase.co"
    assert config.supabase_key == "supa-secret"
    assert config.telegram_bot_token == "bot-token"
    assert config.telegram_chat_id == "-123"
    assert config.environment == "production"


def test_staging_env(monkeypatch, tmp_path):
    """ODOO_ENV=staging reads shared.staging.env."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "shared.staging.env").write_text(
        "ODOO_URL=https://staging.odoo.com\nODOO_DB=stagingdb\n"
    )
    monkeypatch.setattr("puya_odoo_mcp.config.CONFIG_DIR", config_dir)

    creds = tmp_path / "credentials"
    creds.write_text("ODOO_ENV=staging\nODOO_LOGIN=user@test.com\nODOO_API_KEY=key123\n")
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds)

    config = Config()
    assert config.environment == "staging"
    assert config.odoo_url == "https://staging.odoo.com"
    assert config.odoo_db == "stagingdb"


def test_user_creds_override_shared(monkeypatch, tmp_path):
    """User credentials take priority over shared."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "shared.env").write_text("ODOO_URL=https://shared.odoo.com\nODOO_DB=shareddb\n")
    monkeypatch.setattr("puya_odoo_mcp.config.CONFIG_DIR", config_dir)

    creds = tmp_path / "credentials"
    creds.write_text("ODOO_URL=https://override.odoo.com\nODOO_DB=overridedb\n"
                     "ODOO_LOGIN=user@test.com\nODOO_API_KEY=key123\n")
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds)

    config = Config()
    assert config.odoo_url == "https://override.odoo.com"


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


def test_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://test.odoo.com/")
    monkeypatch.setenv("ODOO_DB", "testdb")
    monkeypatch.setenv("ODOO_LOGIN", "user@test.com")
    monkeypatch.setenv("ODOO_API_KEY", "key123")
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"


def test_missing_config():
    with pytest.raises(ConfigError, match="ODOO_URL"):
        Config()


def test_comments_and_blanks_in_file(monkeypatch, tmp_path):
    creds_file = tmp_path / "credentials"
    creds_file.write_text("# Comment\n\n" + FULL_CREDS)
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds_file)
    config = Config()
    assert config.odoo_url == "https://test.odoo.com"


def test_invalid_env(monkeypatch, tmp_path):
    """Unknown environment raises error."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("puya_odoo_mcp.config.CONFIG_DIR", config_dir)

    creds = tmp_path / "credentials"
    creds.write_text("ODOO_ENV=doesnotexist\nODOO_LOGIN=x\nODOO_API_KEY=y\n")
    monkeypatch.setattr("puya_odoo_mcp.config.CREDENTIALS_FILE", creds)

    with pytest.raises(ConfigError, match="doesnotexist"):
        Config()
