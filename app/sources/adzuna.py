from __future__ import annotations

import logging

import httpx

from app.config import Settings
from app.db import Listing
from app.normalize import normalize

log = logging.getLogger(__name__)

BASE = "https://api.adzuna.com/v1/api/jobs/in/search/{page}"


async def fetch_adzuna(
    client: httpx.AsyncClient,
    settings: Settings,
) -> tuple[list[Listing], list[str]]:
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        return [], ["adzuna: skipped (set ADZUNA_APP_ID and ADZUNA_APP_KEY)"]

    listings: list[Listing] = []
    errors: list[str] = []
    seen_urls: set[str] = set()

    # Prefer Delhi/NCR queries first, then India-wide for volume
    locations = settings.adzuna_locations or ["Delhi", "India"]
    # Cap API burn on free tier: key queries × locations × pages
    priority_queries = [
        "associate product manager",
        "product manager intern",
        "product management intern",
        "product intern",
        "junior product manager",
        "APM",
    ]
    broad_queries = ["product manager", "fresher product manager"]

    async def _search(what: str, where: str, pages: int = 2) -> None:
        nonlocal listings
        for page in range(1, pages + 1):
            params: dict = {
                "app_id": settings.adzuna_app_id,
                "app_key": settings.adzuna_app_key,
                "results_per_page": 50,
                "what": what,
                "content-type": "application/json",
            }
            if where:
                params["where"] = where
            url = BASE.format(page=page)
            try:
                resp = await client.get(url, params=params, timeout=25.0)
                if resp.status_code == 401 or resp.status_code == 403:
                    errors.append(f"adzuna: auth failed HTTP {resp.status_code} — check app_id/app_key")
                    return
                if resp.status_code == 429:
                    errors.append("adzuna: rate limited (429) — try again later")
                    return
                if resp.status_code != 200:
                    body = (resp.text or "")[:180]
                    errors.append(f"adzuna/{what}/{where or 'IN'}/p{page}: HTTP {resp.status_code} {body}")
                    break
                data = resp.json()
                results = data.get("results") or []
                if not results:
                    break
                for job in results:
                    company = ""
                    if isinstance(job.get("company"), dict):
                        company = job["company"].get("display_name") or ""
                    location = ""
                    if isinstance(job.get("location"), dict):
                        location = job["location"].get("display_name") or ""
                    salary = None
                    if job.get("salary_min") or job.get("salary_max"):
                        salary = f"INR {job.get('salary_min') or '?'}–{job.get('salary_max') or '?'}"
                    job_url = job.get("redirect_url") or ""
                    if not job_url or job_url in seen_urls:
                        continue
                    item = normalize(
                        title=job.get("title") or "",
                        company=company,
                        location=location,
                        description=job.get("description") or "",
                        url=job_url,
                        source="adzuna",
                        posted_date=job.get("created"),
                        salary=salary,
                    )
                    if item:
                        seen_urls.add(job_url)
                        listings.append(item)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"adzuna/{what}: {exc}")
                log.warning("Adzuna fetch failed: %s", exc)
                break

    # Delhi/NCR first (1 page each) for priority queries
    for what in priority_queries:
        for where in ("Delhi", "Noida", "Greater Noida", "Gurugram", "Gurgaon"):
            await _search(what, where, pages=1)

    # India-wide for volume (2 pages)
    for what in priority_queries + broad_queries:
        await _search(what, "India", pages=2)

    log.info("Adzuna kept %d listings after normalize", len(listings))
    return listings, errors
