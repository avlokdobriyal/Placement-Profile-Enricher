"""
Configuration module for Placement Profile Enricher API.
All tunables are read from environment variables with sensible defaults.
"""

import os
import random
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Rate Limits  (PRD §5 NFR: env var RATE_LIMITS, configurable tokens/second)
# Format: "leetcode:1,codeforces:0.5,linkedin:0.3,github:1"
# ---------------------------------------------------------------------------
_raw_rate_limits = os.getenv(
    "RATE_LIMITS",
    "leetcode:1,codeforces:0.5,linkedin:0.3,github:1",
)

RATE_LIMITS: dict[str, float] = {}
for pair in _raw_rate_limits.split(","):
    platform, rate = pair.strip().split(":")
    RATE_LIMITS[platform.strip().lower()] = float(rate.strip())

# ---------------------------------------------------------------------------
# Request / Retry
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "15"))  # seconds
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "2"))
BACKOFF_BASE: int = int(os.getenv("BACKOFF_BASE", "2"))  # exponential: 2^1, 2^2 …

# ---------------------------------------------------------------------------
# Inter-request delay  (PRD §5 NFR: 750–1250 ms per external request)
# ---------------------------------------------------------------------------
INTER_REQUEST_DELAY_MIN: int = int(os.getenv("INTER_REQUEST_DELAY_MIN", "750"))   # ms
INTER_REQUEST_DELAY_MAX: int = int(os.getenv("INTER_REQUEST_DELAY_MAX", "1250"))  # ms


def get_inter_request_delay() -> float:
    """Return a random delay in *seconds* within [MIN, MAX] ms range."""
    ms = random.randint(INTER_REQUEST_DELAY_MIN, INTER_REQUEST_DELAY_MAX)
    return ms / 1000.0


# ---------------------------------------------------------------------------
# File handling  (PRD §5 NFR: 10 MB limit, streaming >5 MB / >10 k cells)
# ---------------------------------------------------------------------------
MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", str(10 * 1024 * 1024)))  # 10 MB
LARGE_FILE_THRESHOLD_BYTES: int = int(
    os.getenv("LARGE_FILE_THRESHOLD_BYTES", str(5 * 1024 * 1024))
)  # 5 MB
LARGE_FILE_THRESHOLD_CELLS: int = int(
    os.getenv("LARGE_FILE_THRESHOLD_CELLS", "10000")
)

# ---------------------------------------------------------------------------
# Photos directory  (PRD §3 Core Req #4)
# ---------------------------------------------------------------------------
PHOTOS_DIR: str = os.getenv("PHOTOS_DIR", "./photos")

# ---------------------------------------------------------------------------
# Selenium toggle  (PRD §2 Tech Stack – optional)
# ---------------------------------------------------------------------------
SELENIUM_ENABLED: bool = os.getenv("SELENIUM_ENABLED", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Expected column names  (PRD §4 FR: case-insensitive)
# ---------------------------------------------------------------------------
EXPECTED_COLUMNS = ["rollno", "leetcodeurl", "codeforcesurl", "linkedinurl", "githuburl"]

CANONICAL_COLUMNS = {
    "rollno": "RollNo",
    "leetcodeurl": "LeetCodeURL",
    "codeforcesurl": "CodeforcesURL",
    "linkedinurl": "LinkedInURL",
    "githuburl": "GitHubURL",
}

# Enriched column names  (PRD §4 FR – exact names)
ENRICHED_COLUMNS = [
    "LC_Global_Contest_Rank",
    "CF_Rating",
    "Photos_Path",
    "GH_Commits_12mo",
    "GH_Public_Repos",
]

# Enrich_Logs sheet columns  (PRD §4 FR – exact names)
LOG_COLUMNS = ["timestamp", "row_id", "platform", "url", "status", "message"]

# Platform identifiers (used as keys throughout)
PLATFORMS = ["leetcode", "codeforces", "linkedin", "github"]
