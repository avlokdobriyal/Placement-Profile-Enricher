"""
LeetCode scraper – extract global contest rank.
PRD §4 FR: column LC_Global_Contest_Rank; N/A if unavailable, log reason.

NOTE: LeetCode is a React SPA – raw HTML contains no user data for BS4.
We use `requests` (PRD tech stack) to call the public GraphQL endpoint,
which is the only viable non-Selenium approach.
"""

import logging
from datetime import datetime, timezone

import requests

from config import REQUEST_TIMEOUT
from utils import extract_username, validate_and_sanitize_url, BROWSER_HEADERS

logger = logging.getLogger(__name__)

_GRAPHQL_URL = "https://leetcode.com/graphql/"

_CONTEST_QUERY = """
query userContestRankingInfo($username: String!) {
    userContestRanking(username: $username) {
        attendedContestsCount
        rating
        globalRanking
        totalParticipants
        topPercentage
    }
}
"""


def scrape_leetcode(url: str) -> dict:
    """Scrape LeetCode global contest rank for the given profile URL.

    Returns
    -------
    dict
        Keys: ``LC_Global_Contest_Rank``, ``log`` (dict with log entry fields).
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": "leetcode",
        "url": url,
        "status": "error",
        "message": "",
    }

    sanitized = validate_and_sanitize_url(url, "leetcode")
    if not sanitized:
        log_entry["message"] = "Invalid or empty LeetCode URL"
        logger.info("LeetCode: %s", log_entry["message"])
        return {"LC_Global_Contest_Rank": "N/A", "log": log_entry}

    username = extract_username(sanitized, "leetcode")
    if not username:
        log_entry["message"] = "Could not extract username from URL"
        logger.info("LeetCode: %s – %s", log_entry["message"], url)
        return {"LC_Global_Contest_Rank": "N/A", "log": log_entry}

    headers = {
        "Content-Type": "application/json",
        "Referer": "https://leetcode.com",
        "User-Agent": BROWSER_HEADERS["User-Agent"],
    }

    payload = {
        "query": _CONTEST_QUERY,
        "variables": {"username": username},
    }

    logger.info("LeetCode: fetching contest rank for %s", username)
    resp = requests.post(
        _GRAPHQL_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()

    data = resp.json()
    ranking_data = data.get("data", {}).get("userContestRanking")

    if ranking_data is None:
        log_entry["message"] = "User has not participated in any contest"
        log_entry["status"] = "success"
        logger.info("LeetCode: %s – %s", username, log_entry["message"])
        return {"LC_Global_Contest_Rank": "N/A", "log": log_entry}

    global_rank = ranking_data.get("globalRanking")
    if global_rank is None or global_rank == 0:
        log_entry["message"] = "Global ranking not available"
        log_entry["status"] = "success"
        return {"LC_Global_Contest_Rank": "N/A", "log": log_entry}

    log_entry["status"] = "success"
    log_entry["message"] = f"Global contest rank: {global_rank}"
    logger.info("LeetCode: %s – rank %s", username, global_rank)
    return {"LC_Global_Contest_Rank": global_rank, "log": log_entry}
