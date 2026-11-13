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


settings = Settings()
