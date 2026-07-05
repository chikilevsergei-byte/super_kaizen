from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    BOT_TOKEN: str
    DATABASE_URL: str
    WEBHOOK_HOST: str
    LLM_API_KEY: str
    LLM_API_URL: str = "https://api.openai.com/v1"
    ADMIN_ID: int = 0  # Добавили это поле
    GIGACHAT_CREDENTIALS: str
    YANDEX_API_KEY: str
    YANDEX_PROJECT_ID: str
    YANDEX_PROMPT_ID: str

    class Config:
        env_file = ".env"

settings = Settings()