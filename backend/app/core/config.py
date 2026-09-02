from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "OmniNAV"

    database_url: str = (
        "postgresql+asyncpg://omninav_admin:omninav@localhost:5432/omninav"
    )
    redis_url: str = "redis://localhost:6379/0"

    # 通知通道（至少配置一个，否则推送为 no-op 并记录日志）
    feishu_webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # 调度开关（测试/本地调试可关闭）
    enable_scheduler: bool = True

    # 盘中行情缓存 TTL（秒），防止外部 API 限流
    quote_cache_ttl_seconds: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
