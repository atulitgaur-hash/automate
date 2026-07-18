from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    jsearch_api_key: str = ""
    resume_path: str = str(ROOT / "resume.txt")
    database_url: str = f"sqlite:///{ROOT / 'data' / 'jobs.db'}"
    refresh_cron: str = "0 8 * * *"

    # Search focus — India-wide; Delhi/Noida/NCR boosted in scoring
    target_location: str = "Delhi, Noida, India"
    search_queries: list[str] = [
        "associate product manager",
        "product manager intern",
        "product management intern",
        "product intern",
        "junior product manager",
        "fresher product manager",
        "product management trainee",
        "APM",
        "product manager",
    ]
    # Adzuna location params to try (empty = all India on /jobs/in/)
    adzuna_locations: list[str] = [
        "Delhi",
        "Noida",
        "Greater Noida",
        "Gurgaon",
        "Gurugram",
        "India",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
