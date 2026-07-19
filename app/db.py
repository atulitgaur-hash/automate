from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Float, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import get_settings


class JobStatus(str, Enum):
    new = "new"
    reviewed = "reviewed"
    applied = "applied"
    rejected = "rejected"


class Listing(BaseModel):
    """Normalized job listing — single shape for every source."""

    title: str
    company: str
    location: str = ""
    description: str = ""
    url: str
    source: str
    posted_date: Optional[str] = None
    salary: Optional[str] = None
    fit_score: float = 0.0


class ListingOut(Listing):
    status: JobStatus = JobStatus.new
    seen_at: datetime
    updated_at: datetime


class StatusUpdate(BaseModel):
    status: JobStatus


class RefreshResult(BaseModel):
    fetched: int
    upserted: int
    by_source: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class Base(DeclarativeBase):
    pass


class JobListing(Base):
    __tablename__ = "listings"

    url: Mapped[str] = mapped_column(String(1024), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    location: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    posted_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    salary: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    fit_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.new.value, index=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class OutreachStatus(str, Enum):
    pending = "pending"
    drafted = "drafted"
    accepted = "accepted"
    rejected = "rejected"
    sent = "sent"
    failed = "failed"


class OutreachContact(Base):
    __tablename__ = "outreach_contacts"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    company: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    sheet: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=OutreachStatus.pending.value, index=True)
    subject: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


def make_engine():
    import os
    from .config import ROOT

    settings = get_settings()
    url = settings.database_url
    # Vercel filesystem is read-only except /tmp
    if os.getenv("VERCEL") == "1" and url.startswith("sqlite") and "/tmp/" not in url:
        url = "sqlite:////tmp/pm_jobs.db"

    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    if url.startswith("sqlite:///"):
        raw = url.replace("sqlite:///", "", 1)
        db_path = Path(raw)
        if not db_path.is_absolute():
            db_path = (ROOT / db_path).resolve()
            url = f"sqlite:///{db_path}"
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            fallback = Path("/tmp/pm_jobs.db")
            url = f"sqlite:///{fallback}"
            db_path = fallback
            db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, connect_args=connect_args)


# Lazy init so env vars are available before first connection
_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = make_engine()
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def SessionLocal():
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


def init_db() -> None:
    Base.metadata.create_all(bind=get_engine())


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
