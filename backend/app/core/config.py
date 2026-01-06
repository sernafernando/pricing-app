from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str
    
    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080
    
    # ERP API (opcional si no las usás)
    ERP_API_URL: Optional[str] = None
    ERP_API_KEY: Optional[str] = None
    ERP_BASE_URL: str
    ERP_PRODUCTOS_ENDPOINT: str = "/consulta?intExpgr_id=64"
    ERP_STOCK_ENDPOINT: str = "/consulta?opName=ItemStock&intStor_id=1&intItem_id=-1"
    
    # Environment
    ENVIRONMENT: str = "production"
    
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
    
    # GBP Parser (internal service)
    GBP_PARSER_URL: str = "http://localhost:8000/api/gbp-parser"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

settings = Settings()
