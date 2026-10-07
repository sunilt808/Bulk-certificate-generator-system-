from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./certificates.db"
    MEDIA_ROOT: Path = Path("./media")
    MAX_RECIPIENTS_PER_JOB: int = 1000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
