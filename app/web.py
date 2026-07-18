from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings, reload_settings
from .db import JobListing, JobStatus, RefreshResult, SessionLocal, get_db, init_db
from .refresh import run_refresh

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))

IS_VERCEL = os.getenv("VERCEL") == "1"
scheduler = None
if not IS_VERCEL:
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = AsyncIOScheduler()
    except Exception:  # noqa: BLE001
        log.warning("APScheduler unavailable — cron disabled")


def _parse_cron(expr: str):
    if IS_VERCEL or scheduler is None:
        return None
    expr = (expr or "").strip()
    if not expr:
        return None
    parts = expr.split()
    if len(parts) != 5:
        log.warning("Invalid REFRESH_CRON %r — expected 5 fields", expr)
        return None
    from apscheduler.triggers.cron import CronTrigger

    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )


async def _scheduled_refresh() -> None:
    db = SessionLocal()
    try:
        result = await run_refresh(db)
        log.info("Scheduled refresh: %s", result.model_dump())
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    reload_settings()
    try:
        init_db()
    except Exception:
        log.exception("init_db failed")
        raise

    settings = get_settings()
    trigger = _parse_cron(settings.refresh_cron)
    if trigger and scheduler is not None:
        scheduler.add_job(_scheduled_refresh, trigger, id="daily_refresh", replace_existing=True)
        scheduler.start()
        log.info("Scheduler started with cron %s", settings.refresh_cron)
    else:
        log.info("Scheduler disabled (serverless or empty REFRESH_CRON)")
    yield
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="PM Job Pipeline", lifespan=lifespan)

_static_dir = ROOT / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/health")
def health():
    return {
        "ok": True,
        "time": datetime.utcnow().isoformat(),
        "vercel": IS_VERCEL,
    }


@app.post("/api/refresh", response_model=RefreshResult)
async def api_refresh(db: Session = Depends(get_db)):
    reload_settings()
    return await run_refresh(db)


@app.get("/api/listings")
def api_listings(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    source: Optional[str] = None,
    q: Optional[str] = None,
    min_score: float = 0,
    sort: str = "fit_score",
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    stmt = select(JobListing)
    if status and status != "all":
        stmt = stmt.where(JobListing.status == status)
    if source:
        stmt = stmt.where(JobListing.source == source)
    if min_score:
        stmt = stmt.where(JobListing.fit_score >= min_score)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (JobListing.title.ilike(like))
            | (JobListing.company.ilike(like))
            | (JobListing.location.ilike(like))
        )
    sort_col = {
        "fit_score": JobListing.fit_score.desc(),
        "seen_at": JobListing.seen_at.desc(),
        "company": JobListing.company.asc(),
        "title": JobListing.title.asc(),
    }.get(sort, JobListing.fit_score.desc())
    stmt = stmt.order_by(sort_col).offset(offset).limit(limit)
    rows = db.scalars(stmt).all()
    return [
        {
            "url": r.url,
            "title": r.title,
            "company": r.company,
            "location": r.location,
            "source": r.source,
            "posted_date": r.posted_date,
            "salary": r.salary,
            "fit_score": r.fit_score,
            "status": r.status,
            "seen_at": r.seen_at.isoformat() if r.seen_at else None,
            "description": r.description[:500],
        }
        for r in rows
    ]


@app.patch("/api/listings/status")
def api_update_status(url: str, status: JobStatus, db: Session = Depends(get_db)):
    row = db.get(JobListing, url)
    if not row:
        return {"ok": False, "error": "not found"}
    row.status = status.value
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "url": url, "status": row.status}


@app.post("/status")
def form_update_status(
    url: str = Form(...),
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    row = db.get(JobListing, url)
    if row and status in {s.value for s in JobStatus}:
        row.status = status
        row.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/refresh")
async def form_refresh(db: Session = Depends(get_db)):
    reload_settings()
    await run_refresh(db)
    return RedirectResponse(url="/", status_code=303)


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    status: str = "new",
    source: str = "",
    q: str = "",
    sort: str = "fit_score",
    min_score: float = 0,
):
    stmt = select(JobListing)
    if status and status != "all":
        stmt = stmt.where(JobListing.status == status)
    if source:
        stmt = stmt.where(JobListing.source == source)
    if min_score:
        stmt = stmt.where(JobListing.fit_score >= min_score)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (JobListing.title.ilike(like))
            | (JobListing.company.ilike(like))
            | (JobListing.location.ilike(like))
        )
    sort_col = {
        "fit_score": JobListing.fit_score.desc(),
        "seen_at": JobListing.seen_at.desc(),
        "company": JobListing.company.asc(),
    }.get(sort, JobListing.fit_score.desc())
    rows = db.scalars(stmt.order_by(sort_col).limit(200)).all()

    counts = dict(
        db.execute(
            select(JobListing.status, func.count()).group_by(JobListing.status)
        ).all()
    )
    total = sum(counts.values())
    sources = [r[0] for r in db.execute(select(JobListing.source).distinct()).all()]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "jobs": rows,
            "counts": counts,
            "total": total,
            "sources": sources,
            "filters": {
                "status": status,
                "source": source,
                "q": q,
                "sort": sort,
                "min_score": min_score,
            },
            "statuses": [s.value for s in JobStatus],
        },
    )
