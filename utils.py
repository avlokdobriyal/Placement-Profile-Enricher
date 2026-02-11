"""
Utility helpers – URL validation/sanitisation, username extraction, retry wrapper.
PRD §4 FR: validate & sanitize URLs.
PRD §5 NFR: 2 retries with exponential back-off; failures isolated per row/platform.
"""

import re
import time
import logging
from urllib.parse import urlparse, urlunparse
from typing import Any, Callable

import requests

from config import MAX_RETRIES, BACKOFF_BASE, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Common HTTP headers used across scrapers
# ---------------------------------------------------------------------------
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Domain patterns for each platform
# ---------------------------------------------------------------------------
_DOMAIN_PATTERNS: dict[str, re.Pattern] = {
    "leetcode": re.compile(r"^(https?://)?(www\.)?leetcode\.com/", re.IGNORECASE),
    "codeforces": re.compile(r"^(https?://)?(www\.)?codeforces\.com/", re.IGNORECASE),
    "linkedin": re.compile(r"^(https?://)?(www\.)?linkedin\.com/in/", re.IGNORECASE),
    "github": re.compile(r"^(https?://)?(www\.)?github\.com/", re.IGNORECASE),
}

# ---------------------------------------------------------------------------
# Username extraction regexes
# ---------------------------------------------------------------------------
_USERNAME_PATTERNS: dict[str, re.Pattern] = {
    "leetcode": re.compile(
        r"leetcode\.com/(?:u/)?([A-Za-z0-9_-]+)", re.IGNORECASE
    ),
    "codeforces": re.compile(
        r"codeforces\.com/profile/([A-Za-z0-9_.-]+)", re.IGNORECASE
    ),
    "linkedin": re.compile(
        r"linkedin\.com/in/([A-Za-z0-9_-]+)", re.IGNORECASE
    ),
    "github": re.compile(
        r"github\.com/([A-Za-z0-9_-]+)", re.IGNORECASE
    ),
}


# ---------------------------------------------------------------------------
# URL validation & sanitisation  (PRD §5 NFR)
# ---------------------------------------------------------------------------
def validate_and_sanitize_url(url: str | None, platform: str) -> str | None:
    """Return a sanitised URL or *None* if invalid.

    - Strips whitespace / trailing slashes
    - Enforces http(s) scheme only
    - Validates domain matches expected platform
    """
    if not url or not isinstance(url, str):
        return None

    url = url.strip().rstrip("/")

    # Reject dangerous schemes
    if url.lower().startswith(("javascript:", "data:", "file:", "ftp:")):
        logger.warning("Rejected URL with dangerous scheme: %s", url)
        return None

    # Prepend https:// if no scheme
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Parse and re-assemble (normalises structure)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None

    url = urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", "")
    )

    # Check domain
    pattern = _DOMAIN_PATTERNS.get(platform)
    if pattern and not pattern.search(url):
        logger.warning("URL domain mismatch for %s: %s", platform, url)
        return None

    return url


def extract_username(url: str, platform: str) -> str | None:
    """Extract the username / handle from a platform URL."""
    pattern = _USERNAME_PATTERNS.get(platform)
    if not pattern:
        return None
    m = pattern.search(url)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# RollNo fallback  (PRD §4 FR)
# ---------------------------------------------------------------------------
def derive_rollno_fallback(row: dict) -> str:
    """If RollNo is empty, derive an identifier from GitHub or LinkedIn URL."""
    # Try canonical column names first, then case-insensitive fallback
    key_map = {
        "github": ["GitHubURL", "githuburl", "GITHUBURL", "GithubUrl"],
        "linkedin": ["LinkedInURL", "linkedinurl", "LINKEDINURL", "LinkedinUrl"],
    }
    for platform in ("github", "linkedin"):
        url = ""
        for key in key_map[platform]:
            val = row.get(key, "")
            if val:
                url = str(val).strip()
                break
        if not url:
            # Case-insensitive fallback
            for k, v in row.items():
                if k.lower() == key_map[platform][1] and v:
                    url = str(v).strip()
                    break
        username = extract_username(url, platform)
        if username:
            return username
    return "unknown"


# ---------------------------------------------------------------------------
# Retry wrapper  (PRD §5 NFR: 2 retries, exponential back-off, never abort)
# ---------------------------------------------------------------------------
def fetch_with_retry(
    scrape_fn: Callable[..., dict[str, Any]],
    *args: Any,
    max_retries: int = MAX_RETRIES,
    backoff_base: int = BACKOFF_BASE,
    **kwargs: Any,
) -> dict[str, Any]:
    """Call *scrape_fn* with retries.  **Never raises** – returns N/A on failure."""
    last_error = ""
    for attempt in range(1 + max_retries):
        try:
            return scrape_fn(*args, **kwargs)
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Attempt %d/%d failed for %s: %s",
                attempt + 1,
                1 + max_retries,
                scrape_fn.__name__,
                last_error,
            )
            if attempt < max_retries:
                wait = backoff_base ** (attempt + 1)
                time.sleep(wait)
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            logger.error(
                "Unexpected error in %s: %s", scrape_fn.__name__, last_error
            )
            if attempt < max_retries:
                wait = backoff_base ** (attempt + 1)
                time.sleep(wait)

    # All retries exhausted – return structured failure
    return {"error": True, "message": last_error}
