"""
Round-robin scheduler – processes rows across platforms with rate limiting.
PRD §5 NFR: fair round-robin across rows to distribute load.
PRD §6 User Flow #3: rows processed in a round-robin loop, token buckets.
PRD §5 NFR: failures isolated per row/platform, no abort.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any

from config import PLATFORMS, ENRICHED_COLUMNS
from rate_limiter import TokenBucketRateLimiter
from utils import fetch_with_retry, derive_rollno_fallback
from scrapers.leetcode import scrape_leetcode
from scrapers.codeforces import scrape_codeforces
from scrapers.linkedin import scrape_linkedin
from scrapers.github import scrape_github

logger = logging.getLogger(__name__)


def process_rows_round_robin(
    rows: list[dict],
    rate_limiters: dict[str, TokenBucketRateLimiter],
) -> tuple[list[dict], list[dict], dict]:
    """Process all rows with fair round-robin scheduling.

    Iteration order (PRD §6.3 – "fair round-robin across rows"):
        For each platform, cycle through all rows before moving to next platform.
        → row0-LC, row1-LC, ..., rowN-LC, row0-CF, row1-CF, ..., rowN-GH

    Parameters
    ----------
    rows : list[dict]
        Row dicts from the Excel file (normalised column names).
    rate_limiters : dict[str, TokenBucketRateLimiter]
        One rate limiter per platform.

    Returns
    -------
    tuple
        (enriched_data, all_log_records, stats)
        - enriched_data: list of dicts with enriched column values per row
        - all_log_records: flat list of Enrich_Logs dicts
        - stats: per-platform success/error counts + error messages
    """
    total_rows = len(rows)
    start_time = time.time()

    # Initialise result buffers
    enriched_data: list[dict] = [
        {col: "N/A" for col in ENRICHED_COLUMNS} for _ in range(total_rows)
    ]
    all_logs: list[dict] = []

    # Per-platform stats
    stats: dict[str, dict[str, Any]] = {
        p: {"success_count": 0, "error_count": 0, "error_messages": []}
        for p in PLATFORMS
    }

    # Resolve RollNo for each row (PRD §4 FR: fallback)
    rollnos: list[str] = []
    for row in rows:
        rn = row.get("RollNo", "")
        if not rn or (isinstance(rn, float) and str(rn) == "nan"):
            rn = derive_rollno_fallback(row)
        rollnos.append(str(rn).strip())

    # ------------------------------------------------------------------
    # Round-robin: for each platform, process all rows sequentially
    # ------------------------------------------------------------------
    for platform in PLATFORMS:
        logger.info("Scheduler: starting platform=%s for %d rows", platform, total_rows)

        for idx, row in enumerate(rows):
            rollno = rollnos[idx]
            row_id = rollno

            url_key_map = {
                "leetcode": "LeetCodeURL",
                "codeforces": "CodeforcesURL",
                "linkedin": "LinkedInURL",
                "github": "GitHubURL",
            }

            url = row.get(url_key_map[platform], "")
            if not url or (isinstance(url, float) and str(url) == "nan"):
                url = ""

            url = str(url).strip()

            if not url:
                # No URL provided for this platform
                log_entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "row_id": row_id,
                    "platform": platform,
                    "url": "",
                    "status": "error",
                    "message": "No URL provided",
                }
                all_logs.append(log_entry)
                stats[platform]["error_count"] += 1
                stats[platform]["error_messages"].append(
                    f"Row {row_id}: No URL provided"
                )
                continue

            # Acquire rate-limiter token (PRD §5 – token bucket per platform)
            limiter = rate_limiters.get(platform)
            if limiter:
                limiter.acquire()

            # Dispatch to the correct scraper with retry wrapper
            logger.info(
                "Scheduler: row=%s platform=%s url=%s", row_id, platform, url[:80]
            )

            result = _dispatch_scraper(platform, url, rollno)

            # Process results
            if isinstance(result.get("log"), list):
                # GitHub returns a list of log entries
                for log_entry in result["log"]:
                    log_entry["row_id"] = row_id
                    all_logs.append(log_entry)
                    if log_entry["status"] == "success":
                        stats[platform]["success_count"] += 1
                    else:
                        stats[platform]["error_count"] += 1
                        stats[platform]["error_messages"].append(
                            f"Row {row_id}: {log_entry['message']}"
                        )
            elif isinstance(result.get("log"), dict):
                log_entry = result["log"]
                log_entry["row_id"] = row_id
                all_logs.append(log_entry)
                if log_entry["status"] == "success":
                    stats[platform]["success_count"] += 1
                else:
                    stats[platform]["error_count"] += 1
                    stats[platform]["error_messages"].append(
                        f"Row {row_id}: {log_entry['message']}"
                    )
            elif result.get("error"):
                # fetch_with_retry returned a bare error dict
                log_entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "row_id": row_id,
                    "platform": platform,
                    "url": url,
                    "status": "error",
                    "message": result.get("message", "Unknown error"),
                }
                all_logs.append(log_entry)
                stats[platform]["error_count"] += 1
                stats[platform]["error_messages"].append(
                    f"Row {row_id}: {result.get('message', 'Unknown error')}"
                )

            # Write enriched columns into the row buffer
            for col in ENRICHED_COLUMNS:
                if col in result:
                    enriched_data[idx][col] = result[col]

    elapsed_ms = int((time.time() - start_time) * 1000)
    logger.info("Scheduler: completed all rows in %d ms", elapsed_ms)

    # Attach timing to stats
    stats["_total_duration_ms"] = elapsed_ms

    return enriched_data, all_logs, stats


def _dispatch_scraper(platform: str, url: str, rollno: str) -> dict:
    """Call the appropriate scraper through the retry wrapper."""
    if platform == "leetcode":
        return fetch_with_retry(scrape_leetcode, url)
    elif platform == "codeforces":
        return fetch_with_retry(scrape_codeforces, url)
    elif platform == "linkedin":
        return fetch_with_retry(scrape_linkedin, url, rollno)
    elif platform == "github":
        return fetch_with_retry(scrape_github, url)
    else:
        return {"error": True, "message": f"Unknown platform: {platform}"}
