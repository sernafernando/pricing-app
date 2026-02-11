from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 días

    # ERP API (opcional si no las usás)
    ERP_API_URL: Optional[str] = None
    ERP_API_KEY: Optional[str] = None
    ERP_BASE_URL: str
    ERP_PRODUCTOS_ENDPOINT: str = "/consulta?intExpgr_id=64"
    ERP_STOCK_ENDPOINT: str = "/consulta?opName=ItemStock&intStor_id=1&intItem_id=-1"

    # Environment
    ENVIRONMENT: str = "production"

    # CORS — comma-separated origins, e.g. "https://app.example.com,https://admin.example.com"
    # Leave empty to use defaults: permissive in development, restrictive in production.
    CORS_ALLOWED_ORIGINS: str = ""

    @property
    def cors_origins(self) -> List[str]:
        """
        Resolve allowed CORS origins based on environment.

        - If CORS_ALLOWED_ORIGINS is set, use those (any environment).
        - If development and no explicit origins, allow all (localhost convenience).
        - If production and no explicit origins, block everything (fail-safe).
        """
        if self.CORS_ALLOWED_ORIGINS:
            return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
        if self.ENVIRONMENT == "development":
            return ["*"]
        return []

    # Google Sheets
    GOOGLE_SHEETS_ID: str = ""
    GOOGLE_SERVICE_ACCOUNT_FILE: str = "app/credentials/service-account.json"

    # MercadoLibre API
    ML_CLIENT_ID: Optional[str] = None
    ML_CLIENT_SECRET: Optional[str] = None
    ML_USER_ID: Optional[str] = None
    ML_REFRESH_TOKEN: Optional[str] = None

    # Mapbox Geocoding API
    MAPBOX_ACCESS_TOKEN: Optional[str] = None

    # GBP Parser (internal service) - construido desde ERP_BASE_URL
    @property
    def GBP_PARSER_URL(self) -> str:
        """Construye la URL del gbp-parser desde ERP_BASE_URL"""
        return f"{self.ERP_BASE_URL}/gbp-parser"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


settings = Settings()
