from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import JobListing, Listing, RefreshResult
from app.scoring import score_listing
from app.sources.adzuna import fetch_adzuna
from app.sources.greenhouse import fetch_greenhouse
from app.sources.jsearch import fetch_jsearch
from app.sources.lever import fetch_lever

log = logging.getLogger(__name__)


def upsert_listings(db: Session, listings: list[Listing]) -> int:
    now = datetime.utcnow()
    upserted = 0
    for item in listings:
        item.fit_score = score_listing(item)
        existing = db.get(JobListing, item.url)
        if existing:
            existing.title = item.title
            existing.company = item.company
            existing.location = item.location
            existing.description = item.description
            existing.source = item.source
            existing.posted_date = item.posted_date
            existing.salary = item.salary
            existing.fit_score = item.fit_score
            existing.seen_at = now
            existing.updated_at = now
            # keep status
        else:
            db.add(
                JobListing(
                    url=item.url,
                    title=item.title,
                    company=item.company,
                    location=item.location,
                    description=item.description,
                    source=item.source,
                    posted_date=item.posted_date,
                    salary=item.salary,
                    fit_score=item.fit_score,
                    status="new",
                    seen_at=now,
                    updated_at=now,
                )
            )
            upserted += 1
    db.commit()
    return upserted


def prune_stale_matches(db: Session) -> int:
    """Drop rows whose titles no longer pass the target-role filter (e.g. senior leaks)."""
    from app.normalize import is_target_role

    removed = 0
    for row in db.scalars(select(JobListing)).all():
        if not is_target_role(row.title, row.location, row.description):
            db.delete(row)
            removed += 1
    if removed:
        db.commit()
    return removed


async def run_refresh(db: Session) -> RefreshResult:
    settings = get_settings()
    all_listings: list[Listing] = []
    errors: list[str] = []
    by_source: Counter[str] = Counter()

    async with httpx.AsyncClient(
        headers={"User-Agent": "pm-job-pipeline/1.0"},
        follow_redirects=True,
    ) as client:
        for name, coro in (
            ("greenhouse", fetch_greenhouse(client)),
            ("lever", fetch_lever(client)),
            ("adzuna", fetch_adzuna(client, settings)),
            ("jsearch", fetch_jsearch(client, settings)),
        ):
            try:
                items, errs = await coro
                all_listings.extend(items)
                by_source[name] = len(items)
                errors.extend(errs)
                log.info("%s: %d matching listings", name, len(items))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")
                log.exception("Source %s failed", name)

    # Deduplicate by URL within this run
    deduped: dict[str, Listing] = {}
    for item in all_listings:
        if item.url not in deduped or len(item.description) > len(deduped[item.url].description):
            deduped[item.url] = item

    unique = list(deduped.values())
    new_count = upsert_listings(db, unique)
    pruned = prune_stale_matches(db)
    if pruned:
        log.info("Pruned %d listings that no longer match filters", pruned)

    return RefreshResult(
        fetched=len(unique),
        upserted=new_count,
        by_source=dict(by_source),
        errors=errors,
    )
