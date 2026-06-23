from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_env_file(path: Path | None = None, override: bool = False) -> None:
    env_path = path or Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = value


load_env_file()


def _float_env(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _int_env(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def _is_real_secret(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip().lower()
    return bool(normalized) and not normalized.startswith("replace-with") and normalized not in {"none", "null"}


def _mock_env(name: str, api_key: str | None, default: bool = True) -> bool:
    explicit = os.getenv(name)
    if explicit is not None:
        return explicit.lower() == "true"
    if _is_real_secret(api_key):
        return False
    return default


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/wemedia-agent",
        )
    )
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    llm_mock: bool = field(
        default_factory=lambda: _mock_env("LLM_MOCK", os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"))
    )
    image_mock: bool = field(default_factory=lambda: os.getenv("IMAGE_MOCK", "true").lower() == "true")
    checkpointer_mock: bool = field(default_factory=lambda: os.getenv("CHECKPOINTER_MOCK", "false").lower() == "true")
    langsmith_tracing: bool = field(default_factory=lambda: os.getenv("LANGSMITH_TRACING", "false").lower() == "true")
    model_use_system_proxy: bool = field(
        default_factory=lambda: os.getenv("MODEL_USE_SYSTEM_PROXY", "false").lower() == "true"
    )
    llm_api_key: str | None = field(default_factory=lambda: os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"))
    llm_base_url: str = field(
        default_factory=lambda: _first_env("LLM_BASE_URL", "LLM_URL", default="https://api.openai.com/v1")
    )
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4.1-mini"))
    llm_temperature: float = field(default_factory=lambda: _float_env("LLM_TEMPERATURE", 0.4))
    llm_top_p: float = field(default_factory=lambda: _float_env("LLM_TOP_P", 0.9))
    llm_max_tokens: int = field(default_factory=lambda: _int_env("LLM_MAX_TOKENS", 1600))
    llm_presence_penalty: float = field(default_factory=lambda: _float_env("LLM_PRESENCE_PENALTY", 0.1))
    llm_frequency_penalty: float = field(default_factory=lambda: _float_env("LLM_FREQUENCY_PENALTY", 0.1))
    llm_timeout_seconds: int = field(default_factory=lambda: _int_env("LLM_TIMEOUT_SECONDS", 30))
    image_api_key: str | None = field(default_factory=lambda: os.getenv("IMAGE_API_KEY"))
    image_base_url: str = field(default_factory=lambda: os.getenv("IMAGE_BASE_URL", "https://api.openai.com/v1"))
    image_model: str = field(default_factory=lambda: os.getenv("IMAGE_MODEL", "gpt-image-1"))
    embed_mock: bool = field(
        default_factory=lambda: _mock_env("EMBED_MOCK", os.getenv("EMBED_API_KEY") or os.getenv("OPENAI_API_KEY"))
    )
    embed_api_key: str | None = field(
        default_factory=lambda: os.getenv("EMBED_API_KEY") or os.getenv("OPENAI_API_KEY")
    )
    embed_base_url: str = field(
        default_factory=lambda: _first_env("EMBED_BASE_URL", "EMBED_URL", default="https://api.openai.com/v1")
    )
    embed_model: str = field(default_factory=lambda: os.getenv("EMBED_MODEL", "text-embedding-3-small"))
    embed_dimension: int = field(default_factory=lambda: _int_env("EMBED_DIMENSION", 1536))
    langsmith_api_key: str | None = field(default_factory=lambda: os.getenv("LANGSMITH_API_KEY"))
    langsmith_endpoint: str = field(default_factory=lambda: os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"))
    langsmith_project: str = field(default_factory=lambda: os.getenv("LANGSMITH_PROJECT", "wemedia-agent-dev"))
    firecrawl_api_key: str | None = field(default_factory=lambda: os.getenv("FIRECRAWL_API_KEY"))
    firecrawl_base_url: str = field(default_factory=lambda: os.getenv("FIRECRAWL_BASE_URL", "https://api.firecrawl.dev/v2"))
    firecrawl_enabled: bool = field(default_factory=lambda: os.getenv("FIRECRAWL_ENABLED", "false").lower() == "true")
    firecrawl_timeout_seconds: int = field(default_factory=lambda: _int_env("FIRECRAWL_TIMEOUT_SECONDS", 60))
    firecrawl_max_results: int = field(default_factory=lambda: _int_env("FIRECRAWL_MAX_RESULTS", 8))
    wechat_publish_mock: bool = field(default_factory=lambda: os.getenv("WECHAT_PUBLISH_MOCK", "true").lower() == "true")
    wechat_app_id: str = field(default_factory=lambda: os.getenv("WECHAT_APP_ID", ""))
    wechat_app_secret: str = field(default_factory=lambda: os.getenv("WECHAT_APP_SECRET", ""))
    wechat_api_base_url: str = field(
        default_factory=lambda: os.getenv("WECHAT_API_BASE_URL", "https://api.weixin.qq.com")
    )
    wechat_token_cache_seconds: int = field(default_factory=lambda: _int_env("WECHAT_TOKEN_CACHE_SECONDS", 7000))
    wechat_default_thumb_media_id: str = field(default_factory=lambda: os.getenv("WECHAT_DEFAULT_THUMB_MEDIA_ID", ""))
    wechat_publish_default_mode: str = field(default_factory=lambda: os.getenv("WECHAT_PUBLISH_DEFAULT_MODE", "draft"))


settings = Settings()
