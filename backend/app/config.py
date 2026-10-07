from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./certificates.db"
    MEDIA_ROOT: Path = Path("./media")
    MAX_RECIPIENTS_PER_JOB: int = 1000
    PROCESSING_BATCH_SIZE: int = 100
    # Used in QR code links printed on certificates
    BASE_URL: str = "http://localhost:8000"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
