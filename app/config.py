from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    BOT_TOKEN: str
    DATABASE_URL: str = "sqlite+aiosqlite:///./kaizen.db"
    WEBHOOK_HOST: Optional[str] = None
    LLM_API_KEY: Optional[str] = None
    LLM_API_URL: str = "https://api.openai.com/v1"
    ADMIN_ID: int = 0
    GIGACHAT_CREDENTIALS: Optional[str] = None
    YANDEX_API_KEY: Optional[str] = None
    YANDEX_PROJECT_ID: Optional[str] = None
    YANDEX_PROMPT_ID: Optional[str] = None
    ADMIN_PASSWORD: str = "changeme"  # Пароль для веб-админки

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
