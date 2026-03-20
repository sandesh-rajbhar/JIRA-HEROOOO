from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Jira Worklog Assistant"
    log_level: str = "INFO"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    llm_timeout_seconds: int = 45

    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_use_mock: bool = True
    jira_mock_data_path: Path = Field(default=Path("data/mock_jira_tickets.json"))
    jira_cache_ttl_seconds: int = 300
    mapping_confidence_threshold: float = 0.7

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def jira_search_url(self) -> str:
        if not self.jira_base_url:
            raise ValueError("JIRA_BASE_URL is not configured.")
        return f"{self.jira_base_url.rstrip('/')}/rest/api/3/search/jql"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
