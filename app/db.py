from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Float, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import get_settings


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


def make_engine():
    from pathlib import Path

    settings = get_settings()
    url = settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    if url.startswith("sqlite:///"):
        db_path = Path(url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, connect_args=connect_args)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
