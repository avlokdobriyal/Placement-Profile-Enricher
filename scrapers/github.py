"""
GitHub scraper – last-12-month commits and total public repos.
PRD §3 Core Req #2: "Scrape with BeautifulSoup … GitHub last-12-month commits
                      and total public repos."
PRD §4 FR: GH_Commits_12mo (scrape contributions calendar), GH_Public_Repos
           (profile or repositories page); N/A if unavailable; log reason.
"""

import logging
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from utils import extract_username, validate_and_sanitize_url, BROWSER_HEADERS

logger = logging.getLogger(__name__)


def _fetch_contributions(username: str) -> int | None:
    """Fetch 'X contributions in the last year' from the dedicated contributions endpoint.

    GitHub no longer includes contribution counts in the main profile HTML.
    The data lives at ``/users/{username}/contributions``.
    """
    url = f"https://github.com/users/{username}/contributions"
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # The page contains text like "3,152 contributions in the last year"
    h2_tags = soup.find_all("h2")
    for h2 in h2_tags:
        text = h2.get_text(strip=True)
        m = re.search(r"([\d,]+)\s+contributions?\s+in the last year", text, re.IGNORECASE)
        if m:
            return int(m.group(1).replace(",", ""))

    # Fallback: search anywhere in the page
    page_text = soup.get_text()
    m = re.search(r"([\d,]+)\s+contributions?\s+in the last year", page_text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))

    return None


def _parse_public_repos(soup: BeautifulSoup, username: str) -> int | None:
    """Extract total public repos from the profile nav tab."""
    # Look for the "Repositories" tab with a counter
    # <a href="/username?tab=repositories" ...><span ...>Repositories</span><span ...>42</span></a>
    repo_link = soup.find("a", href=re.compile(r"\?tab=repositories", re.IGNORECASE))
    if repo_link:
        counter = repo_link.find("span", class_=re.compile(r"Counter", re.IGNORECASE))
        if counter:
            try:
                return int(counter.get_text(strip=True).replace(",", ""))
            except ValueError:
                pass

    # Fallback: look for any span/text after "Repositories"
    nav = soup.find("nav", attrs={"aria-label": re.compile(r"user profile", re.IGNORECASE)})
    if nav:
        items = nav.find_all("a")
        for item in items:
            text = item.get_text(strip=True)
            m = re.search(r"Repositories\s*([\d,]+)", text)
            if m:
                return int(m.group(1).replace(",", ""))

    return None


def scrape_github(url: str) -> dict:
    """Scrape GitHub profile for contributions and public repos.

    Returns
    -------
    dict
        Keys: ``GH_Commits_12mo``, ``GH_Public_Repos``, ``log`` (list of log dicts).
    """
    log_entries = []
    now = datetime.now(timezone.utc).isoformat()

    def _log(col: str, status: str, message: str) -> dict:
        entry = {
            "timestamp": now,
            "platform": "github",
            "url": url,
            "status": status,
            "message": f"[{col}] {message}",
        }
        log_entries.append(entry)
        return entry

    sanitized = validate_and_sanitize_url(url, "github")
    if not sanitized:
        _log("GH_Commits_12mo", "error", "Invalid or empty GitHub URL")
        _log("GH_Public_Repos", "error", "Invalid or empty GitHub URL")
        return {
            "GH_Commits_12mo": "N/A",
            "GH_Public_Repos": "N/A",
            "log": log_entries,
        }

    username = extract_username(sanitized, "github")
    if not username:
        _log("GH_Commits_12mo", "error", "Could not extract username from URL")
        _log("GH_Public_Repos", "error", "Could not extract username from URL")
        return {
            "GH_Commits_12mo": "N/A",
            "GH_Public_Repos": "N/A",
            "log": log_entries,
        }

    logger.info("GitHub: fetching profile for %s", username)

    resp = requests.get(
        f"https://github.com/{username}",
        headers=BROWSER_HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # ----- Contributions in last 12 months (PRD: "scrape contributions calendar") -----
    commits = _fetch_contributions(username)
    if commits is not None:
        _log("GH_Commits_12mo", "success", f"Contributions (last 12 mo): {commits}")
        logger.info("GitHub: %s – %d contributions", username, commits)
    else:
        _log("GH_Commits_12mo", "error", "Could not parse contributions from profile")
        logger.info("GitHub: %s – contributions not found", username)

    # ----- Total public repositories -----
    repos = _parse_public_repos(soup, username)
    if repos is not None:
        _log("GH_Public_Repos", "success", f"Public repos: {repos}")
        logger.info("GitHub: %s – %d public repos", username, repos)
    else:
        _log("GH_Public_Repos", "error", "Could not parse public repos from profile")
        logger.info("GitHub: %s – public repos not found", username)

    return {
        "GH_Commits_12mo": commits if commits is not None else "N/A",
        "GH_Public_Repos": repos if repos is not None else "N/A",
        "log": log_entries,
    }
