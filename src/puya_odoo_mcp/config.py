import os


class ConfigError(Exception):
    pass


class Config:
    def __init__(self):
        self.odoo_url = os.environ.get("ODOO_URL", "").rstrip("/")
        self.odoo_db = os.environ.get("ODOO_DB", "")
        self.odoo_api_key = os.environ.get("ODOO_API_KEY", "")

        missing = []
        if not self.odoo_url:
            missing.append("ODOO_URL")
        if not self.odoo_db:
            missing.append("ODOO_DB")
        if not self.odoo_api_key:
            missing.append("ODOO_API_KEY")

        if missing:
            raise ConfigError(
                f"Missing required environment variables: {', '.join(missing)}"
            )
