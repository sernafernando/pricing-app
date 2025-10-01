from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str
    
    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    
    # ERP
    ERP_BASE_URL: str
    ERP_PRODUCTOS_ENDPOINT: str
    ERP_STOCK_ENDPOINT: str
    
    # App
    ENVIRONMENT: str = "production"
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
