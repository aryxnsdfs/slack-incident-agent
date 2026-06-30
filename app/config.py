from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ContextOps"
    public_base_url: str = "http://127.0.0.1:8000"
    demo_mode: bool = True

    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_realtime_search_method: str = "search.messages"
    slack_search_count: int = 5

    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    aws_region: str = "us-east-1"
    cloudwatch_log_group: str = "/aws/ecs/payment-api"
    cloudwatch_filter_pattern: str = "ERROR ?Exception ?Timeout ?500"
    s3_report_bucket: str = ""

    database_url: str = "sqlite+aiosqlite:///./contextops.db"

    contextops_mcp_mode: str = Field(default="direct", pattern="^(direct|stdio)$")
    mcp_tool_timeout_seconds: int = 20

    local_report_dir: Path = Path("reports")


@lru_cache
def get_settings() -> Settings:
    return Settings()
