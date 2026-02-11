"""
Test happy path – PRD §5 NFR: minimal tests covering a happy-path row.

Tests:
- All 4 scrapers return valid data (mocked)
- Enriched Excel has correct columns and values
- Enrich_Logs sheet has expected structure
- summary.json has all required fields
- ZIP contains enriched.xlsx and summary.json
"""

import json
import zipfile
import pytest
from io import BytesIO
from unittest.mock import patch

import pandas as pd
from openpyxl import Workbook

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import app
from config import ENRICHED_COLUMNS, LOG_COLUMNS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_excel() -> bytes:
    """Create a minimal test Excel with one row."""
    wb = Workbook()
    ws = wb.active
    ws.append(["RollNo", "LeetCodeURL", "CodeforcesURL", "LinkedInURL", "GitHubURL"])
    ws.append([
        "2021001",
        "https://leetcode.com/u/testuser",
        "https://codeforces.com/profile/testuser",
        "https://www.linkedin.com/in/testuser",
        "https://github.com/testuser",
    ])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Mock scraper return values
# ---------------------------------------------------------------------------

_MOCK_LC = {
    "LC_Global_Contest_Rank": 1234,
    "log": {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "platform": "leetcode",
        "url": "https://leetcode.com/u/testuser",
        "status": "success",
        "message": "Global contest rank: 1234",
    },
}

_MOCK_CF = {
    "CF_Rating": 1567,
    "log": {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "platform": "codeforces",
        "url": "https://codeforces.com/profile/testuser",
        "status": "success",
        "message": "Current rating: 1567",
    },
}

_MOCK_LI = {
    "Photos_Path": "photos/2021001.jpg",
    "log": {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "platform": "linkedin",
        "url": "https://www.linkedin.com/in/testuser",
        "status": "success",
        "message": "Photo saved to photos/2021001.jpg",
    },
}

_MOCK_GH = {
    "GH_Commits_12mo": 523,
    "GH_Public_Repos": 15,
    "log": [
        {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "platform": "github",
            "url": "https://github.com/testuser",
            "status": "success",
            "message": "[GH_Commits_12mo] Contributions (last 12 mo): 523",
        },
        {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "platform": "github",
            "url": "https://github.com/testuser",
            "status": "success",
            "message": "[GH_Public_Repos] Public repos: 15",
        },
    ],
}


def _mock_scrape_leetcode(url):
    return _MOCK_LC

def _mock_scrape_codeforces(url):
    return _MOCK_CF

def _mock_scrape_linkedin(url, rollno):
    return _MOCK_LI

def _mock_scrape_github(url):
    return _MOCK_GH


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHappyPath:
    """Full end-to-end with mocked scrapers."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.client = app.test_client()

    @patch("scheduler.scrape_github", _mock_scrape_github)
    @patch("scheduler.scrape_linkedin", _mock_scrape_linkedin)
    @patch("scheduler.scrape_codeforces", _mock_scrape_codeforces)
    @patch("scheduler.scrape_leetcode", _mock_scrape_leetcode)
    def test_full_enrich(self):
        excel_bytes = _make_test_excel()

        response = self.client.post(
            "/enrich",
            data={"excel": (BytesIO(excel_bytes), "test.xlsx")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 200
        assert response.content_type == "application/zip"

        # ---- Unzip ----
        zf = zipfile.ZipFile(BytesIO(response.data))
        assert "enriched.xlsx" in zf.namelist()
        assert "summary.json" in zf.namelist()

        # ---- Check enriched.xlsx ----
        xlsx_bytes = zf.read("enriched.xlsx")
        df = pd.read_excel(BytesIO(xlsx_bytes), sheet_name="Sheet1")

        # Original columns preserved
        assert "RollNo" in df.columns
        assert "LeetCodeURL" in df.columns

        # Enriched columns present with correct values
        assert "LC_Global_Contest_Rank" in df.columns
        assert df["LC_Global_Contest_Rank"].iloc[0] == 1234

        assert "CF_Rating" in df.columns
        assert df["CF_Rating"].iloc[0] == 1567

        assert "Photos_Path" in df.columns
        assert df["Photos_Path"].iloc[0] == "photos/2021001.jpg"

        assert "GH_Commits_12mo" in df.columns
        assert df["GH_Commits_12mo"].iloc[0] == 523

        assert "GH_Public_Repos" in df.columns
        assert df["GH_Public_Repos"].iloc[0] == 15

        # ---- Check Enrich_Logs sheet ----
        df_logs = pd.read_excel(BytesIO(xlsx_bytes), sheet_name="Enrich_Logs")
        for col in LOG_COLUMNS:
            assert col in df_logs.columns, f"Missing log column: {col}"
        assert len(df_logs) > 0

        # ---- Check summary.json ----
        summary = json.loads(zf.read("summary.json"))
        assert "total_rows" in summary
        assert summary["total_rows"] == 1
        assert "total_duration_ms" in summary
        assert isinstance(summary["total_duration_ms"], int)
        assert "overall_success_rate" in summary
        assert "platforms" in summary

        for platform in ["leetcode", "codeforces", "linkedin", "github"]:
            p = summary["platforms"][platform]
            assert "success_rate" in p
            assert "error_count" in p
            assert "sample_errors" in p
            assert isinstance(p["sample_errors"], list)

    def test_missing_file_field(self):
        response = self.client.post("/enrich", content_type="multipart/form-data")
        assert response.status_code == 400

    def test_wrong_extension(self):
        response = self.client.post(
            "/enrich",
            data={"excel": (BytesIO(b"not excel"), "test.csv")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 400
