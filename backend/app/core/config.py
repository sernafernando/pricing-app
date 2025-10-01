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
    ERP_PRODUCTOS_ENDPOINT: str = "/consulta?intExpgr_id=64"
    ERP_STOCK_ENDPOINT: str = "/consulta?opName=ItemStock&intStor_id=1&intItem_id=-1"
    
    # Environment
    ENVIRONMENT: str = "production"
    
    # Google Sheets
    GOOGLE_SHEETS_ID: str = ""
    GOOGLE_SERVICE_ACCOUNT_FILE: str = "app/credentials/service-account.json"
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

settings = Settings()
