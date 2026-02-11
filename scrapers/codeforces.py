"""
Codeforces scraper – extract current rating via HTML scraping with BeautifulSoup.
PRD §3 Core Req #2: "Scrape platform metrics with BeautifulSoup."
PRD §4 FR: column CF_Rating; N/A if unavailable, log reason.

Primary method: BS4 HTML scraping of the profile page.
Fallback: Codeforces public REST API (still using `requests` from PRD tech stack).
"""

import logging
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from utils import extract_username, validate_and_sanitize_url, BROWSER_HEADERS

logger = logging.getLogger(__name__)


def _scrape_rating_html(handle: str) -> int | None:
    """Try to scrape the current rating from the Codeforces profile page HTML."""
    profile_url = f"https://codeforces.com/profile/{handle}"
    resp = requests.get(
        profile_url, headers=BROWSER_HEADERS, timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # The rating is shown in a <span> inside the info div with class "user-rating"
    # or as the first value in the info list. Several possible selectors:
    # 1) <span style="font-weight:bold;" ...>  beneath the rating info section
    # 2) Look for text "Contest rating:" followed by the value
    info_items = soup.find_all("span", class_="user-gray") + \
                 soup.find_all("span", class_="user-green") + \
                 soup.find_all("span", class_="user-cyan") + \
                 soup.find_all("span", class_="user-blue") + \
                 soup.find_all("span", class_="user-violet") + \
                 soup.find_all("span", class_="user-orange") + \
                 soup.find_all("span", class_="user-red") + \
                 soup.find_all("span", class_="user-legendary")

    # The main info section usually has: "Contest rating: XXXX"
    info_div = soup.find("div", class_="info")
    if info_div:
        text = info_div.get_text()
        m = re.search(r"Contest rating:\s*(\d+)", text)
        if m:
            return int(m.group(1))

    # Fallback: look for the rating in the main-info span
    rating_span = soup.select_one("div.info ul li span")
    if rating_span:
        try:
            return int(rating_span.get_text(strip=True))
        except ValueError:
            pass

    return None


def _scrape_rating_api(handle: str) -> int | None:
    """Fallback: fetch rating from the public Codeforces REST API."""
    api_url = f"https://codeforces.com/api/user.info?handles={handle}"
    resp = requests.get(api_url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "OK":
        return None

    results = data.get("result", [])
    if not results:
        return None

    user = results[0]
    return user.get("rating")  # None if user is unrated


def scrape_codeforces(url: str) -> dict:
    """Scrape Codeforces current rating for the given profile URL.

    Returns
    -------
    dict
        Keys: ``CF_Rating``, ``log`` (dict with log entry fields).
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": "codeforces",
        "url": url,
        "status": "error",
        "message": "",
    }

    sanitized = validate_and_sanitize_url(url, "codeforces")
    if not sanitized:
        log_entry["message"] = "Invalid or empty Codeforces URL"
        logger.info("Codeforces: %s", log_entry["message"])
        return {"CF_Rating": "N/A", "log": log_entry}

    handle = extract_username(sanitized, "codeforces")
    if not handle:
        # Try extracting from path directly
        parts = sanitized.rstrip("/").split("/")
        handle = parts[-1] if parts else None

    if not handle:
        log_entry["message"] = "Could not extract handle from URL"
        logger.info("Codeforces: %s – %s", log_entry["message"], url)
        return {"CF_Rating": "N/A", "log": log_entry}

    logger.info("Codeforces: fetching rating for %s", handle)

    # Primary: BS4 HTML scraping (PRD §3.2)
    rating = None
    try:
        rating = _scrape_rating_html(handle)
        if rating is not None:
            logger.info("Codeforces: %s – rating %d (HTML)", handle, rating)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Codeforces HTML scrape failed for %s: %s", handle, exc)

    # Fallback: REST API
    if rating is None:
        try:
            rating = _scrape_rating_api(handle)
            if rating is not None:
                logger.info("Codeforces: %s – rating %d (API fallback)", handle, rating)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Codeforces API fallback failed for %s: %s", handle, exc)

    if rating is None:
        log_entry["message"] = "User is unrated or rating could not be retrieved"
        log_entry["status"] = "success"
        logger.info("Codeforces: %s – %s", handle, log_entry["message"])
        return {"CF_Rating": "N/A", "log": log_entry}

    log_entry["status"] = "success"
    log_entry["message"] = f"Current rating: {rating}"
    return {"CF_Rating": rating, "log": log_entry}
