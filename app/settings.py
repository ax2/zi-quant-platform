from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg:///postgres?host=/var/run/postgresql"
    host: str = "127.0.0.1"
    port: int = 8092
    qveris_data_api_key: str = ""
    qveris_base_url: str = "https://qveris.ai/api/v1"
    qveris_prepared_search_id: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    deepseek_timeout_seconds: float = 120.0
    github_token: str = ""
    zi_api_token: str = ""
    zi_deployment_mode: str = "development"
    auto_create_schema: bool = True
    min_public_pool_real_bar_coverage: float = 0.18
    min_public_pool_long_history_coverage: float = 0.12
    min_public_pool_financial_coverage: float = 0.12
    min_public_pool_real_bar_symbols: int = 90
    min_public_pool_long_history_symbols: int = 60
    min_public_pool_financial_symbols: int = 60
    max_fallback_bar_ratio: float = 0.05
    lark_cli_bin: str = "lark-cli"
    lark_signal_chat_id: str = "oc_68db16641907e192c8cfd23e55d6c1ac"
    lark_signal_live_enabled: bool = False
    lark_signal_default_dry_run: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
