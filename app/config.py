from functools import lru_cache
from pathlib import Path
import os

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


def _default_database_url() -> str:
    # Vercel only allows writes under /tmp (ephemeral between cold starts)
    if os.getenv("VERCEL") == "1":
        return "sqlite:////tmp/pm_jobs.db"
    return f"sqlite:///{ROOT / 'data' / 'jobs.db'}"


def _default_refresh_cron() -> str:
    # Background schedulers don't work reliably on serverless
    if os.getenv("VERCEL") == "1":
        return ""
    return "0 8 * * *"


def _default_resume_pdf_path() -> str:
    # Prefer tracked asset so deploys have the file without Drive.
    bundled = ROOT / "assets" / "Kiriti_Nain_Resume.pdf"
    if bundled.exists():
        return str(bundled)
    # Vercel is read-only except /tmp — cache Drive downloads there
    if os.getenv("VERCEL") == "1":
        return "/tmp/Kiriti_Nain_Resume.pdf"
    return str(ROOT / "data" / "Kiriti_Nain_Resume.pdf")


def _default_outreach_excel_path() -> str:
    # Contact source — tracked in repo for deploys
    bundled = ROOT / "assets" / "contacts.xlsx"
    if bundled.exists():
        return str(bundled)
    legacy = ROOT / "data" / "Copy of System 2.xlsx"
    if legacy.exists():
        return str(legacy)
    return str(bundled)


def _default_outreach_tracker_path() -> str:
    # Tracker is writable state — must use /tmp on Vercel
    if os.getenv("VERCEL") == "1":
        return "/tmp/outreach_tracker.xlsx"
    return str(ROOT / "data" / "outreach_tracker.xlsx")


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
    database_url: str = _default_database_url()
    refresh_cron: str = _default_refresh_cron()

    # Outreach / email automation
    openai_api_key: str = ""
    openai_model: str = "gpt-5.1"
    kiriti_profile_path: str = str(ROOT / "kiriti_profile.txt")
    gmail_address: str = "kitinain@gmail.com"
    gmail_app_password: str = ""
    gmail_smtp_host: str = "smtp.gmail.com"
    gmail_smtp_port: int = 587
    outreach_excel_path: str = _default_outreach_excel_path()
    outreach_tracker_path: str = _default_outreach_tracker_path()
    # PDF resume attached to every outreach email (tracked under assets/)
    resume_pdf_path: str = _default_resume_pdf_path()
    resume_drive_file_id: str = "1zfSViW_5GqFtupzYOJvQiydflPc9v-Fl"

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
