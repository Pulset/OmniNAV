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

    # 首管理员 seed（sys_users 为空时由迁移 0003 创建；不开放公开注册）
    init_admin_username: str = "admin"
    init_admin_password: str | None = None

    # 会话 Cookie：生产前置 HTTPS 时置 true
    cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
