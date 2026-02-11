"""
Test failure row – PRD §5 NFR: minimal tests covering a failure row.

Tests:
- All scrapers raise exceptions
- N/A values written in all enriched columns
- Enrich_Logs sheet has error entries
- Job does NOT abort – response is still 200 with valid ZIP
- summary.json reflects errors
"""

import json
import zipfile
import pytest
from io import BytesIO
from unittest.mock import patch, MagicMock

import pandas as pd
from openpyxl import Workbook

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import app
from config import ENRICHED_COLUMNS, LOG_COLUMNS

import requests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_excel() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["RollNo", "LeetCodeURL", "CodeforcesURL", "LinkedInURL", "GitHubURL"])
    ws.append([
        "FAIL001",
        "https://leetcode.com/u/doesnotexist999",
        "https://codeforces.com/profile/doesnotexist999",
        "https://www.linkedin.com/in/doesnotexist999",
        "https://github.com/doesnotexist999",
    ])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Mock scrapers that always fail
# ---------------------------------------------------------------------------

def _failing_leetcode(url):
    raise requests.ConnectionError("Mocked connection error")

def _failing_codeforces(url):
    raise requests.Timeout("Mocked timeout")

def _failing_linkedin(url, rollno):
    raise requests.HTTPError("Mocked 999 response")

def _failing_github(url):
    raise requests.ConnectionError("Mocked DNS failure")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFailureRow:
    """All scrapers fail – job should still complete."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.client = app.test_client()

    @patch("time.sleep", return_value=None)  # skip backoff waits
    @patch("scheduler.scrape_github", _failing_github)
    @patch("scheduler.scrape_linkedin", _failing_linkedin)
    @patch("scheduler.scrape_codeforces", _failing_codeforces)
    @patch("scheduler.scrape_leetcode", _failing_leetcode)
    def test_all_scrapers_fail(self, mock_sleep):
        excel_bytes = _make_test_excel()

        response = self.client.post(
            "/enrich",
            data={"excel": (BytesIO(excel_bytes), "test.xlsx")},
            content_type="multipart/form-data",
        )

        # PRD §5 NFR: failures isolated, job not aborted
        assert response.status_code == 200
        assert response.content_type == "application/zip"

        zf = zipfile.ZipFile(BytesIO(response.data))
        assert "enriched.xlsx" in zf.namelist()
        assert "summary.json" in zf.namelist()

        # ---- N/A values everywhere ----
        xlsx_bytes = zf.read("enriched.xlsx")
        # keep_default_na=False so Pandas doesn't convert "N/A" text to NaN
        df = pd.read_excel(BytesIO(xlsx_bytes), sheet_name="Sheet1", keep_default_na=False)

        for col in ENRICHED_COLUMNS:
            assert col in df.columns
            val = str(df[col].iloc[0])
            assert val == "N/A", f"Expected N/A for {col}, got {val}"

        # ---- Enrich_Logs has error entries ----
        df_logs = pd.read_excel(BytesIO(xlsx_bytes), sheet_name="Enrich_Logs")
        for col_name in LOG_COLUMNS:
            assert col_name in df_logs.columns
        assert len(df_logs) > 0

        error_logs = df_logs[df_logs["status"] == "error"]
        assert len(error_logs) > 0, "Expected error entries in Enrich_Logs"

        # ---- summary.json reflects errors ----
        summary = json.loads(zf.read("summary.json"))
        assert summary["total_rows"] == 1

        for platform in ["leetcode", "codeforces", "linkedin", "github"]:
            p = summary["platforms"][platform]
            assert p["error_count"] > 0, f"Expected errors for {platform}"
            assert p["success_rate"] == 0.0

    @patch("time.sleep", return_value=None)  # skip backoff waits
    @patch("scheduler.scrape_github", _failing_github)
    @patch("scheduler.scrape_linkedin", _failing_linkedin)
    @patch("scheduler.scrape_codeforces", _failing_codeforces)
    @patch("scheduler.scrape_leetcode", _failing_leetcode)
    def test_partial_failure_multiple_rows(self, mock_sleep):
        """Verify that one row failing does not block other rows."""
        wb = Workbook()
        ws = wb.active
        ws.append(["RollNo", "LeetCodeURL", "CodeforcesURL", "LinkedInURL", "GitHubURL"])
        ws.append(["ROW1", "https://leetcode.com/u/user1",
                    "https://codeforces.com/profile/user1",
                    "https://www.linkedin.com/in/user1",
                    "https://github.com/user1"])
        ws.append(["ROW2", "https://leetcode.com/u/user2",
                    "https://codeforces.com/profile/user2",
                    "https://www.linkedin.com/in/user2",
                    "https://github.com/user2"])
        buf = BytesIO()
        wb.save(buf)

        response = self.client.post(
            "/enrich",
            data={"excel": (BytesIO(buf.getvalue()), "test.xlsx")},
            content_type="multipart/form-data",
        )

        # Both rows should be processed even though all scrapers fail
        assert response.status_code == 200

        zf = zipfile.ZipFile(BytesIO(response.data))
        xlsx_bytes = zf.read("enriched.xlsx")
        df = pd.read_excel(BytesIO(xlsx_bytes), sheet_name="Sheet1", keep_default_na=False)

        assert len(df) == 2, "Both rows should be present"
        for col in ENRICHED_COLUMNS:
            assert str(df[col].iloc[0]) == "N/A"
            assert str(df[col].iloc[1]) == "N/A"

        summary = json.loads(zf.read("summary.json"))
        assert summary["total_rows"] == 2
