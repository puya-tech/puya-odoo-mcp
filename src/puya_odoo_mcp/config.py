import os
from pathlib import Path

CREDENTIALS_DIR = Path.home() / ".config" / "puya-odoo-mcp"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials"
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


class ConfigError(Exception):
    pass


def _read_env_file(path: Path) -> dict:
    """Read key=value pairs from a file."""
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


class Config:
    def __init__(self):
        # Layer 1: User credentials file (read early to get ODOO_ENV)
        user_creds = _read_env_file(CREDENTIALS_FILE)

        # Determine environment: credentials > env var > default (production)
        env = user_creds.get("ODOO_ENV") or os.environ.get("ODOO_ENV", "production")
        if env == "production":
            shared_file = CONFIG_DIR / "shared.env"
        else:
            shared_file = CONFIG_DIR / f"shared.{env}.env"
            if not shared_file.exists():
                raise ConfigError(
                    f"Environment '{env}' config not found: {shared_file}"
                )

        # Layer 2: Shared config from repo (public values)
        shared = _read_env_file(shared_file)
        self.environment = env

        # Layer 3: Environment variables (fallback)
        # Priority: user_creds > shared > env vars
        def _get(key: str) -> str:
            return user_creds.get(key) or shared.get(key) or os.environ.get(key, "")

        # Odoo (URL/DB from shared, login/key from user)
        self.odoo_url = _get("ODOO_URL").rstrip("/")
        self.odoo_db = _get("ODOO_DB")
        self.odoo_login = _get("ODOO_LOGIN")
        self.odoo_api_key = _get("ODOO_API_KEY")

        # Supabase (URL from shared, service key from user)
        self.supabase_url = _get("SUPABASE_URL").rstrip("/")
        self.supabase_key = _get("SUPABASE_SERVICE_KEY")

        # Telegram (chat_id from shared, bot token from user)
        self.telegram_bot_token = _get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = _get("TELEGRAM_CHAT_ID")

        # Validate required Odoo config
        missing = []
        if not self.odoo_url:
            missing.append("ODOO_URL")
        if not self.odoo_db:
            missing.append("ODOO_DB")
        if not self.odoo_login:
            missing.append("ODOO_LOGIN")
        if not self.odoo_api_key:
            missing.append("ODOO_API_KEY")

        if missing:
            raise ConfigError(
                f"Missing config: {', '.join(missing)}. "
                f"Add to {CREDENTIALS_FILE} or as env vars."
            )

    @staticmethod
    def list_environments() -> list[Path]:
        """List available shared environment files."""
        return sorted(CONFIG_DIR.glob("shared*.env"))
