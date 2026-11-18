from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str = Field(min_length=32)

    db_echo: bool = False
    pool_size: int = 5
    pool_max_overflow: int = 10
    pool_recycle: int = 1800
    pool_pre_ping: bool = True
    jwt_expire_minutes: int = 60

    s3_region: str
    s3_bucket_name: str
    s3_public_url: str | None = None
    s3_api_url: str | None = None

    project_size_limit_bytes: int = Field(default=50 * 1024 * 1024, gt=0)

    ses_api_url: str | None = None
    sender_email: str = "noreply@projects.local"
    frontend_url: str = "http://localhost:8080"
    invitation_ttl_hours: int = Field(default=168, gt=0)


settings = Settings()
