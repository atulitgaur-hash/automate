from __future__ import annotations

import logging

import httpx

from app.config import Settings
from app.db import Listing
from app.normalize import normalize

log = logging.getLogger(__name__)

BASE = "https://jsearch.p.rapidapi.com/search"


async def fetch_jsearch(
    client: httpx.AsyncClient,
    settings: Settings,
) -> tuple[list[Listing], list[str]]:
    if not settings.jsearch_api_key:
        return [], ["jsearch: skipped (set JSEARCH_API_KEY)"]

    listings: list[Listing] = []
    errors: list[str] = []
    headers = {
        "x-rapidapi-key": settings.jsearch_api_key,
        "x-rapidapi-host": "jsearch.p.rapidapi.com",
    }

    for query in settings.search_queries:
        params = {
            "query": f"{query} in Delhi OR Noida, India",
            "page": "1",
            "num_pages": "1",
            "country": "in",
            "date_posted": "month",
        }
        try:
            resp = await client.get(BASE, headers=headers, params=params, timeout=30.0)
            if resp.status_code != 200:
                errors.append(f"jsearch/{query}: HTTP {resp.status_code}")
                continue
            data = resp.json()
            for job in data.get("data") or []:
                salary = None
                if job.get("job_min_salary") or job.get("job_max_salary"):
                    currency = job.get("job_salary_currency") or "INR"
                    salary = f"{currency} {job.get('job_min_salary') or '?'}–{job.get('job_max_salary') or '?'}"
                url = (
                    job.get("job_apply_link")
                    or job.get("job_google_link")
                    or job.get("job_employer_website")
                    or ""
                )
                item = normalize(
                    title=job.get("job_title") or "",
                    company=job.get("employer_name") or "",
                    location=job.get("job_city")
                    or job.get("job_location")
                    or job.get("job_country")
                    or "",
                    description=job.get("job_description") or "",
                    url=url,
                    source="jsearch",
                    posted_date=job.get("job_posted_at_datetime_utc")
                    or str(job.get("job_posted_at_timestamp") or "")
                    or None,
                    salary=salary,
                )
                if item:
                    listings.append(item)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"jsearch/{query}: {exc}")
            log.warning("JSearch fetch failed: %s", exc)

    return listings, errors
