from __future__ import annotations

import html
import re
from typing import Optional

from .db import Listing

# Target band: fresher / 0–2 years only
MAX_YEARS_EXPERIENCE = 2.0

JUNIOR_TITLE = re.compile(
    r"""
    (
      associate\s+product\s+manager
      | product\s+manager\s+(intern|trainee|graduate|apprentice|associate)
      | (pm|product)\s+(intern|trainee)
      | junior\s+product\s+manager
      | fresher.{0,40}product\s+manager
      | product\s+management\s+(intern|trainee|associate|graduate)
      | graduate\s+(product\s+manager|apm)
      | entry[- ]level\s+product\s+manager
      | product\s+associate
      | product\s+analyst
      | apm\s+(program|intern|associate|trainee)?
    )
    """,
    re.I | re.X,
)

# Non-senior Product Manager — kept only when India-relevant
PLAIN_PM = re.compile(r"\bproduct\s+managers?\b", re.I)

SENIOR_BLOCKLIST = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|head|director|vp|vice\s+president|"
    r"group\s+product|gpm|team\s+lead|10\+?\s*years|8\+?\s*years)\b",
    re.I,
)

# Datadog-style "APM" = Application Performance Monitoring, not Associate PM
APM_FALSE_POSITIVE = re.compile(
    r"\b(performance|monitoring|observability|engineering|engineer|server|apm\s+experiences?)\b",
    re.I,
)

INDIA_LOCATION = re.compile(
    r"\b(india|delhi|ncr|noida|gurgaon|gurugram|bangalore|bengaluru|"
    r"mumbai|hyderabad|pune|chennai|kolkata|ahmedabad|jaipur|"
    r"remote\s*[-–—]?\s*india|india\s*[-–—]?\s*remote)\b",
    re.I,
)

DELHI_BOOST = re.compile(
    r"\b(delhi|ncr|noida|greater\s+noida|ghaziabad|gurgaon|gurugram|new\s+delhi)\b",
    re.I,
)

# Explicit non-India geo — used to drop US/EU-only mid PM roles
NON_INDIA_ONLY = re.compile(
    r"\b(united\s+states|usa|uk|london|san\s+francisco|seattle|new\s+york|nyc|"
    r"toronto|vancouver|warsaw|tel\s+aviv|stockholm|emea)\b",
    re.I,
)

FRESHER_SIGNAL = re.compile(
    r"\b("
    r"fresher|freshers|entry[- ]level|campus\s+hire|graduate\s+hire|"
    r"no\s+prior\s+experience|no\s+experience\s+required|"
    r"0\s*[-–—to]+\s*[12]\s*(?:years?|yrs?)|"
    r"1\s*[-–—to]+\s*2\s*(?:years?|yrs?)|"
    r"(?:up\s*to|upto|under|less\s+than|<)\s*2\s*(?:years?|yrs?)|"
    r"intern|internship|trainee|apprentice"
    r")\b",
    re.I,
)

# "3-5 years", "2 – 4 yrs"
EXP_RANGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[-–—to]+\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b",
    re.I,
)
# "3+ years", "5+ yrs experience"
EXP_PLUS = re.compile(
    r"(\d+(?:\.\d+)?)\s*\+\s*(?:years?|yrs?)\b",
    re.I,
)
# "minimum 3 years", "at least 4 years of experience"
EXP_MIN_PHRASE = re.compile(
    r"(?:minimum|min\.?|at\s+least|requires?|must\s+have|should\s+have|"
    r"with\s+at\s+least)\s+(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)",
    re.I,
)
# "3 years of experience", "4 years experience in product"
EXP_YEARS_OF = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience|exp\.?)\b",
    re.I,
)


def _blob(*parts: str) -> str:
    return " ".join(p for p in parts if p)


def _is_intern_or_trainee_title(title: str) -> bool:
    return bool(
        re.search(
            r"\b(intern|internship|trainee|apprentice|fresher|graduate\s+hire|campus)\b",
            title,
            re.I,
        )
    )


def _is_apm_title(title: str) -> bool:
    if re.search(r"associate\s+product\s+manager", title, re.I):
        return True
    if re.search(r"\bapm\b", title, re.I):
        if APM_FALSE_POSITIVE.search(title):
            return False
        # Bare "APM" alone is ok; "APM- Civil" / non-product APM is not
        if re.search(r"\bapm\b.{0,20}\b(civil|audio|mechanical|construction|site)\b", title, re.I):
            return False
        # Prefer titles that also mention product / associate / program
        if re.search(r"product|associate|program|intern|graduate", title, re.I):
            return True
        # Title is essentially just APM / APM - Something product-ish
        if re.fullmatch(r"\s*apm\s*", title, re.I) or re.match(r"^\s*apm\b", title, re.I):
            return True
        return False
    return False


def _is_junior_title(title: str) -> bool:
    if _is_apm_title(title):
        return True
    if JUNIOR_TITLE.search(title):
        # Extra guard: bare "apm" already handled; reject observability hits inside junior regex
        if re.search(r"\bapm\b", title, re.I) and APM_FALSE_POSITIVE.search(title):
            return False
        return True
    return False


def fits_experience_band(title: str, description: str = "") -> bool:
    """Keep only roles aimed at 0–2 years / fresher / intern.

    Rejects when the JD's stated minimum experience is above 2 years.
    Intern/trainee titles always pass (JDs sometimes paste senior boilerplate).
    """
    if _is_intern_or_trainee_title(title):
        return True

    text = _blob(title, description[:3500])
    if not text.strip():
        return True

    # Explicit fresher / 0-2 in the title → keep
    if FRESHER_SIGNAL.search(title):
        return True

    mins: list[float] = []

    for m in EXP_RANGE.finditer(text):
        lo, hi = float(m.group(1)), float(m.group(2))
        mins.append(min(lo, hi))

    for m in EXP_PLUS.finditer(text):
        mins.append(float(m.group(1)))

    for m in EXP_MIN_PHRASE.finditer(text):
        mins.append(float(m.group(1)))

    for m in EXP_YEARS_OF.finditer(text):
        mins.append(float(m.group(1)))

    if not mins:
        # No numeric years found — keep junior/APM titles; drop plain PM without fresher signal
        if _is_junior_title(title) or FRESHER_SIGNAL.search(text):
            return True
        return False

    required_min = min(mins)
    if required_min > MAX_YEARS_EXPERIENCE:
        return False
    return True


def is_india_relevant(location: str = "", description: str = "", title: str = "") -> bool:
    blob = _blob(title, location, description[:2500])
    return bool(INDIA_LOCATION.search(blob))


def is_target_role(title: str, location: str = "", description: str = "") -> bool:
    """PM intern / APM / junior PM (0–2 YOE), India-focused."""
    if not title:
        return False

    junior = _is_junior_title(title)
    plain_pm = bool(PLAIN_PM.search(title)) and not SENIOR_BLOCKLIST.search(title)

    if not junior and not plain_pm:
        return False

    # Drop senior/lead variants unless the title is clearly an APM/intern track
    if SENIOR_BLOCKLIST.search(title):
        if not re.search(
            r"associate\s+product\s+manager|\bapm\b|product\s+manager\s+intern|"
            r"product\s+intern|junior\s+product\s+manager",
            title,
            re.I,
        ):
            return False

    if not fits_experience_band(title, description):
        return False

    india = is_india_relevant(location, description, title)

    if junior:
        # Keep junior/intern/APM if India-tagged OR location unknown
        if location and NON_INDIA_ONLY.search(location) and not india:
            return False
        return True

    if plain_pm:
        # Plain PM: require India in the location field + 0-2 YOE (checked above)
        if location and INDIA_LOCATION.search(location):
            return True
        if not location and INDIA_LOCATION.search(description[:2500]):
            return True
        return False

    return False


def location_relevance(location: str, description: str = "") -> float:
    blob = _blob(location, description[:1500])
    if DELHI_BOOST.search(blob):
        return 1.0
    if INDIA_LOCATION.search(blob):
        return 0.75
    return 0.35


def clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize(
    *,
    title: str,
    company: str,
    location: str = "",
    description: str = "",
    url: str,
    source: str,
    posted_date: Optional[str] = None,
    salary: Optional[str] = None,
) -> Optional[Listing]:
    title = clean_text(title)
    company = clean_text(company)
    location = clean_text(location)
    description = clean_text(description)
    url = (url or "").strip()
    if not title or not url:
        return None
    if not is_target_role(title, location, description):
        return None
    return Listing(
        title=title,
        company=company or "Unknown",
        location=location,
        description=description[:8000],
        url=url,
        source=source,
        posted_date=posted_date,
        salary=salary,
    )
