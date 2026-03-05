import os
from pathlib import Path

CREDENTIALS_DIR = Path.home() / ".config" / "puya-odoo-mcp"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials"


class ConfigError(Exception):
    pass


def _read_credentials_file() -> dict:
    """Read key=value pairs from ~/.config/puya-odoo-mcp/credentials."""
    if not CREDENTIALS_FILE.exists():
        return {}
    values = {}
    for line in CREDENTIALS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


class Config:
    def __init__(self):
        creds = _read_credentials_file()

        # Credentials file takes priority, env vars as fallback
        self.odoo_url = (creds.get("ODOO_URL") or os.environ.get("ODOO_URL", "")).rstrip("/")
        self.odoo_db = creds.get("ODOO_DB") or os.environ.get("ODOO_DB", "")
        self.odoo_api_key = creds.get("ODOO_API_KEY") or os.environ.get("ODOO_API_KEY", "")

        missing = []
        if not self.odoo_url:
            missing.append("ODOO_URL")
        if not self.odoo_db:
            missing.append("ODOO_DB")
        if not self.odoo_api_key:
            missing.append("ODOO_API_KEY")

        if missing:
            raise ConfigError(
                f"Missing config. Set in {CREDENTIALS_FILE} or as env vars: {', '.join(missing)}"
            )
