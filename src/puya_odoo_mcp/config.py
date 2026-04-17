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
        # Track whether ODOO_ENV was explicitly set (vs defaulting to production)
        _explicit_env = user_creds.get("ODOO_ENV") or os.environ.get("ODOO_ENV")
        env = _explicit_env or "production"
        if env == "production":
            shared_file = CONFIG_DIR / "shared.env"
        else:
            shared_file = CONFIG_DIR / f"shared.{env}.env"

        # Layer 2: Shared config from repo (public values)
        # Optional — when running via pip install or Docker, these files
        # may not exist. Env vars alone are sufficient.
        shared = _read_env_file(shared_file) if shared_file.exists() else {}

        # Layer 3: Environment variables (highest priority when set)
        # Priority: env vars > user_creds > shared
        # This allows agent-vault, Docker, CI, etc. to inject secrets
        # without needing the credentials file.
        def _get(key: str) -> str:
            return os.environ.get(key) or user_creds.get(key) or shared.get(key) or ""

        # Odoo (URL/DB from shared, login/key from user)
        self.odoo_url = _get("ODOO_URL").rstrip("/")
        self.odoo_db = _get("ODOO_DB")
        self.odoo_login = _get("ODOO_LOGIN")
        self.odoo_api_key = _get("ODOO_API_KEY")

        # Determine effective environment:
        # If ODOO_ENV was explicitly set (credentials file, env var, agent-vault),
        # use it directly — no URL heuristic needed.
        # Otherwise, detect by comparing URL to production shared.env.
        if _explicit_env:
            self.environment = env
        else:
            prod_url = shared.get("ODOO_URL", "").rstrip("/")
            if prod_url and self.odoo_url and self.odoo_url != prod_url:
                # URL was overridden to something other than production
                self.environment = "custom"
                # Try to match against known staging configs
                for env_file in sorted(CONFIG_DIR.glob("shared.*.env")):
                    env_config = _read_env_file(env_file)
                    if env_config.get("ODOO_URL", "").rstrip("/") == self.odoo_url:
                        # Extract env name: shared.staging.env → staging
                        self.environment = env_file.stem.replace("shared.", "")
                        break
            else:
                self.environment = "production"

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
