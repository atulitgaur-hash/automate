from __future__ import annotations

import logging
from typing import Optional

import httpx

from ..companies import GREENHOUSE_COMPANIES
from ..db import Listing
from ..normalize import normalize

log = logging.getLogger(__name__)

BASE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


async def fetch_greenhouse(
    client: httpx.AsyncClient,
    companies: Optional[list[str]] = None,
) -> tuple[list[Listing], list[str]]:
    listings: list[Listing] = []
    errors: list[str] = []
    tokens = companies or GREENHOUSE_COMPANIES

    for token in tokens:
        url = BASE.format(token=token)
        try:
            resp = await client.get(url, params={"content": "true"}, timeout=20.0)
            if resp.status_code == 404:
                continue
            if resp.status_code != 200:
                errors.append(f"greenhouse/{token}: HTTP {resp.status_code}")
                continue
            data = resp.json()
            company_name = data.get("name") or token.replace("-", " ").title()
            for job in data.get("jobs", []):
                locs = job.get("location", {}) or {}
                location = locs.get("name") or ""
                if isinstance(job.get("offices"), list) and not location:
                    location = ", ".join(
                        o.get("name", "") for o in job["offices"] if o.get("name")
                    )
                item = normalize(
                    title=job.get("title") or "",
                    company=company_name,
                    location=location,
                    description=job.get("content") or "",
                    url=job.get("absolute_url") or "",
                    source="greenhouse",
                    posted_date=job.get("updated_at") or job.get("created_at"),
                )
                if item:
                    listings.append(item)
        except Exception as exc:  # noqa: BLE001 — isolate per-company failures
            errors.append(f"greenhouse/{token}: {exc}")
            log.warning("Greenhouse fetch failed for %s: %s", token, exc)

    return listings, errors
