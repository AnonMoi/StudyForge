from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./data/learning_workstation.db"
    local_model_base_url: str = "http://127.0.0.1:11434/v1"
    local_model_name: str = "qwen35-9b-local:latest"
    local_model_api_key: str = ""
    cloud_model_base_url: str = "https://zhi-api.com/v1"
    cloud_model_name: str = "gpt-5.6-luna"
    cloud_model_api_key: str = ""
    cloud_model_enabled: bool = False
    model_routing_mode: str = "local_first"
    daily_cloud_call_limit: int = 20
    daily_cost_limit: float = 2.0
    max_tokens_per_request: int = 12000
    local_model_timeout_seconds: float = 60.0
    local_confidence_threshold: float = 0.65
    model_max_retries: int = 1
    model_retry_backoff_seconds: float = 0.0
    model_cache_ttl_seconds: int = 3600
    report_model_enhancement_enabled: bool = False
    cloud_input_price_per_1k: float = 0.02
    cloud_output_price_per_1k: float = 0.06
    max_input_chars: int = 120000
    log_prompts: bool = False
    redact_sensitive_data: bool = True
    provider_billing_enabled: bool = False
    provider_billing_provider: str = "zhiapi"
    provider_billing_url: str = ""
    provider_billing_api_key: str = ""
    provider_billing_timeout_seconds: float = 15.0
    provider_billing_max_retries: int = 2
    provider_billing_auto_sync: bool = False
    provider_billing_sync_interval_hours: int = 24
    learning_scheduler_interval_seconds: int = 60
    web_push_enabled: bool = False
    web_push_vapid_public_key: str = ""
    web_push_vapid_private_key: str = ""
    web_push_subject: str = "mailto:local@learning-workstation.invalid"
    web_push_ttl_seconds: int = 3600
    native_notifications_enabled: bool = False
    cloud_sync_enabled: bool = False
    cloud_sync_provider: str = "webdav"
    cloud_sync_url: str = ""
    cloud_sync_username: str = ""
    cloud_sync_password: str = ""
    cloud_sync_path: str = "learning-workstation/sync.json"
    cloud_sync_timeout_seconds: float = 15.0
    cors_allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4174,http://localhost:4174"
    api_allowed_hosts: str = "127.0.0.1,localhost,testserver"
    max_request_body_bytes: int = 2_000_000
    api_workers: int = 1
    github_enabled: bool = True
    github_api_base_url: str = "https://api.github.com"
    github_token: str = ""
    github_timeout_seconds: float = 15.0

    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parents[2] / ".env"),
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origins(self) -> list[str]:
        return _split_csv(self.cors_allowed_origins)

    @property
    def allowed_hosts(self) -> list[str]:
        return _split_csv(self.api_allowed_hosts)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    path = project_root() / ".." / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def database_path() -> Path:
    return data_dir() / "learning_workstation.db"


def resolve_database_url(database_url: str) -> str:
    """Move only the shipped default SQLite database into the shared data directory.

    Other relative SQLite URLs are intentional overrides, most commonly isolated
    development or browser-test databases, and must not be redirected to live data.
    """
    if database_url == "sqlite:///./data/learning_workstation.db":
        return f"sqlite:///{database_path().as_posix()}"
    return database_url


def masked_key(value: str) -> str:
    if not value:
        return "未配置"
    return "********"


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def validate_runtime_config(config: Settings | None = None) -> dict[str, Any]:
    current = config or settings
    errors: list[str] = []
    warnings: list[str] = []
    environment = str(current.app_env or "").strip().lower()
    production_like = environment in {"staging", "production"}
    origins = current.cors_origins
    hosts = current.allowed_hosts
    database_url = str(current.database_url or "").strip()
    cloud_url = str(current.cloud_model_base_url or "").strip().lower()
    github_url = str(current.github_api_base_url or "").strip().lower()
    cloud_sync_url = str(current.cloud_sync_url or "").strip()

    if environment not in {"development", "test", "staging", "production"}:
        errors.append("APP_ENV 必须是 development、test、staging 或 production")
    if not database_url or "://" not in database_url:
        errors.append("DATABASE_URL 未配置或格式无效")
    if not origins or "*" in origins:
        errors.append("CORS_ALLOWED_ORIGINS 必须配置明确来源，不能使用通配符")
    if not hosts or "*" in hosts:
        errors.append("API_ALLOWED_HOSTS 必须配置明确主机，不能使用通配符")
    if production_like and "testserver" in hosts:
        errors.append("生产环境 API_ALLOWED_HOSTS 不能包含测试主机 testserver")
    if current.max_request_body_bytes < 64 * 1024:
        errors.append("MAX_REQUEST_BODY_BYTES 不能小于 65536")
    if current.learning_scheduler_interval_seconds < 5:
        errors.append("LEARNING_SCHEDULER_INTERVAL_SECONDS 不能小于 5")
    if current.web_push_ttl_seconds < 60 or current.web_push_ttl_seconds > 2_419_200:
        errors.append("WEB_PUSH_TTL_SECONDS 必须在 60 到 2419200 秒之间")
    if current.web_push_enabled and (not current.web_push_vapid_public_key or not current.web_push_vapid_private_key):
        errors.append("启用后台推送时必须配置 WEB_PUSH_VAPID_PUBLIC_KEY 和 WEB_PUSH_VAPID_PRIVATE_KEY")
    if current.web_push_enabled and not str(current.web_push_subject).startswith(("mailto:", "https://")):
        errors.append("WEB_PUSH_SUBJECT 必须是 mailto 或 HTTPS 地址")
    if current.cloud_sync_provider != "webdav":
        errors.append("当前只支持 WEB_DAV 云同步适配器")
    if current.cloud_sync_enabled and (not cloud_sync_url or not current.cloud_sync_username or not current.cloud_sync_password):
        errors.append("启用云同步时必须配置 CLOUD_SYNC_URL、CLOUD_SYNC_USERNAME 和 CLOUD_SYNC_PASSWORD")
    if current.cloud_sync_enabled:
        try:
            sync_url = urlsplit(cloud_sync_url)
            if sync_url.scheme not in {"http", "https"} or not sync_url.hostname or sync_url.username or sync_url.password:
                errors.append("CLOUD_SYNC_URL 必须是不含账号信息的 HTTP/HTTPS 地址")
            else:
                _ = sync_url.port
        except ValueError:
            errors.append("CLOUD_SYNC_URL 端口格式无效")
    if current.cloud_sync_enabled and production_like and not cloud_sync_url.lower().startswith("https://"):
        errors.append("生产环境云同步必须使用 HTTPS")
    if ".." in str(current.cloud_sync_path).replace("\\", "/").split("/"):
        errors.append("CLOUD_SYNC_PATH 不能包含父目录路径")
    if current.cloud_sync_timeout_seconds <= 0 or current.cloud_sync_timeout_seconds > 120:
        errors.append("CLOUD_SYNC_TIMEOUT_SECONDS 必须在 0 到 120 秒之间")
    if current.api_workers < 1:
        errors.append("API_WORKERS 必须大于等于 1")
    if current.api_workers > 1:
        errors.append("当前单用户后台调度模型要求 API_WORKERS=1")
    if current.github_enabled and not github_url.startswith(("http://", "https://")):
        errors.append("GITHUB_API_BASE_URL 必须是 HTTP/HTTPS 地址")
    if current.github_timeout_seconds <= 0 or current.github_timeout_seconds > 120:
        errors.append("GITHUB_TIMEOUT_SECONDS 必须在 0 到 120 秒之间")
    if current.cloud_model_enabled and not current.cloud_model_api_key:
        errors.append("启用云端模型时必须配置 CLOUD_MODEL_API_KEY")
    if current.cloud_model_enabled:
        try:
            model_url = urlsplit(cloud_url)
            if model_url.scheme not in {"http", "https"} or not model_url.hostname or model_url.username or model_url.password or model_url.query or model_url.fragment:
                errors.append("CLOUD_MODEL_BASE_URL 必须是不含凭据、查询参数和片段的 HTTP/HTTPS 地址")
            else:
                _ = model_url.port
        except ValueError:
            errors.append("CLOUD_MODEL_BASE_URL 端口格式无效")
    if current.cloud_model_enabled and production_like and not cloud_url.startswith("https://"):
        errors.append("生产环境启用云端模型时 CLOUD_MODEL_BASE_URL 必须使用 HTTPS")
    if current.provider_billing_auto_sync and not current.provider_billing_enabled:
        errors.append("启用账单自动同步时必须启用供应商账单功能")
    if current.provider_billing_enabled and (not current.provider_billing_url or not current.provider_billing_api_key):
        errors.append("启用供应商账单时必须配置账单接口地址和密钥")
    if production_like and not current.redact_sensitive_data:
        errors.append("生产环境必须启用敏感信息脱敏")

    if not current.cloud_model_enabled:
        warnings.append("云端模型当前关闭，复杂任务不会自动发送到云端")
    if database_url.lower().startswith("sqlite") and production_like:
        warnings.append("生产环境使用 SQLite，请配置外部备份并保持单 worker")
    if not current.local_model_name:
        warnings.append("本地模型名称为空，本地模型任务将不可用")

    return {
        "valid": not errors,
        "environment": environment,
        "errors": errors,
        "warnings": warnings,
        "checks": {
            "database": {"configured": bool(database_url), "driver": database_url.split(":", 1)[0] if database_url else None},
            "cloud_model": {"enabled": bool(current.cloud_model_enabled), "key_configured": bool(current.cloud_model_api_key), "https": cloud_url.startswith("https://")},
            "privacy": {"redact_sensitive_data": bool(current.redact_sensitive_data)},
            "cors": {"origins_count": len(origins), "wildcard": "*" in origins},
            "hosts": {"hosts_count": len(hosts), "wildcard": "*" in hosts},
            "runtime": {"max_request_body_bytes": current.max_request_body_bytes, "scheduler_interval_seconds": current.learning_scheduler_interval_seconds, "api_workers": current.api_workers, "web_push_enabled": bool(current.web_push_enabled), "cloud_sync_enabled": bool(current.cloud_sync_enabled)},
        },
    }


settings = get_settings()
settings.database_url = resolve_database_url(settings.database_url)


__all__ = ["Settings", "settings", "masked_key", "resolve_database_url", "validate_runtime_config"]
