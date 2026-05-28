from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str
    # Conexión directa a PostgreSQL (bypasses PgBouncer).
    # Requerida para DDL/migrations (Alembic). Si no está seteada, usa DATABASE_URL.
    DATABASE_URL_DIRECT: Optional[str] = None

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
    GOOGLE_CAJA_ID: str = ""
    GOOGLE_SERVICE_ACCOUNT_FILE: str = "app/credentials/service-account.json"

    # Caja (Cash Register) — file uploads
    CAJA_UPLOADS_PATH: str = "./uploads/caja/"

    # MercadoLibre API
    ML_CLIENT_ID: Optional[str] = None
    ML_CLIENT_SECRET: Optional[str] = None
    ML_USER_ID: Optional[str] = None
    ML_REFRESH_TOKEN: Optional[str] = None

    # ML Webhook Database (para consultar ml_previews directamente)
    ML_WEBHOOK_DB_URL: Optional[str] = None

    # Mapbox Geocoding API
    MAPBOX_ACCESS_TOKEN: Optional[str] = None

    # Redis (for SSE pub/sub fan-out)
    REDIS_URL: str = "redis://localhost:6379/0"
    SSE_HEARTBEAT_SECONDS: int = 30
    SSE_MAX_CONNECTIONS: int = 100

    # GBP (ERP SOAP credentials)
    GBP_USERNAME: Optional[str] = None
    GBP_PASSWORD: Optional[str] = None
    GBP_COMPANY: Optional[str] = None
    GBP_WEBWS: str = "wsBasicQuery"

    # Tienda Nube
    TN_STORE_ID: Optional[str] = None
    TN_ACCESS_TOKEN: Optional[str] = None

    # GBP Parser (internal service) - SIEMPRE localhost porque corre en el mismo servidor
    GBP_PARSER_URL: str = "http://localhost:8002/api/gbp-parser"

    # OpenWeatherMap API (free tier: 1000 calls/day)
    # Docs: https://openweathermap.org/current
    OPENWEATHER_API_KEY: Optional[str] = None
    # Felipe Vallese 1559, CABA (depósito / centro de distribución)
    OPENWEATHER_LAT: float = -34.61684231394052
    OPENWEATHER_LON: float = -58.456197873190796

    # RRHH — Recursos Humanos
    RRHH_UPLOADS_DIR: str = "uploads/rrhh"
    RRHH_MAX_FILE_SIZE_MB: int = 10

    # Tickets — Adjuntos
    TICKETS_UPLOADS_DIR: str = "uploads/tickets"
    TICKETS_MAX_FILE_SIZE_MB: int = 5

    # Compras — Adjuntos (pedidos de compra + órdenes de pago)
    # Los archivos se guardan como:
    #   {COMPRAS_UPLOADS_DIR}/{entidad_tipo}/{entidad_id}/{uuid}_{filename}
    # entidad_tipo ∈ {pedido_compra, orden_pago}.
    COMPRAS_UPLOADS_DIR: str = "uploads/compras"
    COMPRAS_MAX_FILE_SIZE_MB: int = 20

    # Hikvision DS-K1T804 (access control terminal — ISAPI over HTTP + Digest Auth)
    HIKVISION_HOST: Optional[str] = None
    HIKVISION_PORT: int = 80
    HIKVISION_USERNAME: Optional[str] = None
    HIKVISION_PASSWORD: Optional[str] = None

    # AFIP SDK (afipsdk.com — Padrón A4, Constancia de Inscripción)
    AFIP_CUIT: Optional[str] = None
    AFIP_ACCESS_TOKEN: Optional[str] = None
    AFIP_SDK_BASE_URL: str = "https://app.afipsdk.com/api/v1/afip"
    AFIP_ENVIRONMENT: str = "prod"  # "dev" para testing con CUIT 20409378472
    # Certificado digital de producción (generado con scripts/setup_afip_cert.py)
    AFIP_CERT: Optional[str] = None
    AFIP_KEY: Optional[str] = None

    # Prearmados stats cache
    PREARMADAS_STATS_CACHE_TTL_SECONDS: int = 15
    PREARMADAS_STATS_VOLUME_WARN: int = 5000

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


settings = Settings()
