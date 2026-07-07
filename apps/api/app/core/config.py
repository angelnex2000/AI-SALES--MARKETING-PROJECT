from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    OPENAI_API_KEY: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"
    """Celery broker/result backend for background AI jobs (Module 9)."""
    ENCRYPTION_KEY: str = ""
    """Fernet key for encrypting integration OAuth tokens at rest. Generate
    with `Fernet.generate_key()` — required before any Integration with
    credentials is created."""

    class Config:
        env_file = ".env"


settings = Settings()
