# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    # Banco separado do operacional: guarda 15 dias de série histórica 
    historico_database_url: str
    historico_dias: int = 15
    redemet_base_url: str
    redemet_api_key: str
    # AISWEB (DECEA): nascer/pôr do sol e presença de torre, para o VFR Especial
    aisweb_base_url: str = "https://api.decea.mil.br/aisweb/"
    aisweb_api_key: str = ""
    aisweb_api_pass: str = ""
    collector_interval_minutes: int = 60
    db_echo: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8020"]
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
