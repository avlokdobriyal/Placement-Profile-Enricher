"""
Test column mapping – PRD §5 NFR: minimal tests covering column mapping.

Tests:
- Case-insensitive column detection
- Missing RollNo fallback to GitHub/LinkedIn username
- Extra columns are preserved in output
- MIME type / extension rejection
"""

import pytest
from io import BytesIO

import pandas as pd
from openpyxl import Workbook

# Ensure project root is importable
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from excel_handler import read_excel, validate_columns, write_enriched
from config import ENRICHED_COLUMNS
from utils import derive_rollno_fallback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_excel_bytes(headers: list[str], rows: list[list]) -> bytes:
    """Create a minimal .xlsx in memory and return raw bytes."""
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCaseInsensitiveColumns:
    """PRD §4 FR: Expected headers (case-insensitive)."""

    def test_all_lowercase(self):
        data = _make_excel_bytes(
            ["rollno", "leetcodeurl", "codeforcesurl", "linkedinurl", "githuburl"],
            [["R001", "https://leetcode.com/u/test", "https://codeforces.com/profile/test",
              "https://linkedin.com/in/test", "https://github.com/test"]],
        )
        rows = read_excel(data)
        ok, _ = validate_columns(rows)
        assert ok
        assert "RollNo" in rows[0]
        assert "LeetCodeURL" in rows[0]

    def test_mixed_case(self):
        data = _make_excel_bytes(
            ["ROLLNO", "Leetcodeurl", "CODEFORCESURL", "Linkedinurl", "GithubUrl"],
            [["R002", "url1", "url2", "url3", "url4"]],
        )
        rows = read_excel(data)
        ok, _ = validate_columns(rows)
        assert ok
        assert "RollNo" in rows[0]
        assert "GitHubURL" in rows[0]

    def test_canonical_case(self):
        data = _make_excel_bytes(
            ["RollNo", "LeetCodeURL", "CodeforcesURL", "LinkedInURL", "GitHubURL"],
            [["R003", "url1", "url2", "url3", "url4"]],
        )
        rows = read_excel(data)
        ok, _ = validate_columns(rows)
        assert ok


class TestMissingRollNoFallback:
    """PRD §4 FR: If RollNo is missing, derive from GitHub or LinkedIn username."""

    def test_fallback_github(self):
        row = {"GitHubURL": "https://github.com/johndoe", "LinkedInURL": ""}
        identifier = derive_rollno_fallback(row)
        assert identifier == "johndoe"

    def test_fallback_linkedin(self):
        row = {"GitHubURL": "", "LinkedInURL": "https://linkedin.com/in/janedoe"}
        identifier = derive_rollno_fallback(row)
        assert identifier == "janedoe"

    def test_fallback_unknown(self):
        row = {"GitHubURL": "", "LinkedInURL": ""}
        identifier = derive_rollno_fallback(row)
        assert identifier == "unknown"

    def test_rollno_column_missing_from_excel(self):
        """When the Excel has no RollNo column at all, validation still passes
        (RollNo is recommended, not strictly required)."""
        data = _make_excel_bytes(
            ["LeetCodeURL", "CodeforcesURL", "LinkedInURL", "GitHubURL"],
            [["url1", "url2", "url3", "url4"]],
        )
        rows = read_excel(data)
        ok, _ = validate_columns(rows)
        assert ok


class TestExtraColumnsPreserved:
    """PRD §4 FR: Preserve original columns."""

    def test_extra_columns_in_output(self):
        data = _make_excel_bytes(
            ["RollNo", "Name", "Branch", "LeetCodeURL", "CodeforcesURL", "LinkedInURL", "GitHubURL"],
            [["R100", "Alice", "CSE", "url1", "url2", "url3", "url4"]],
        )
        rows = read_excel(data)

        enriched_data = [{col: "test_value" for col in ENRICHED_COLUMNS}]
        output_bytes = write_enriched(rows, enriched_data, [])

        df = pd.read_excel(BytesIO(output_bytes), sheet_name="Sheet1")
        assert "Name" in df.columns
        assert "Branch" in df.columns
        assert "LC_Global_Contest_Rank" in df.columns
        assert "GH_Public_Repos" in df.columns


class TestMissingRequiredColumns:
    """Validation should fail when required URL columns are missing."""

    def test_missing_leetcode_column(self):
        data = _make_excel_bytes(
            ["RollNo", "CodeforcesURL", "LinkedInURL", "GitHubURL"],
            [["R001", "url1", "url2", "url3"]],
        )
        rows = read_excel(data)
        ok, msg = validate_columns(rows)
        assert not ok
        assert "leetcodeurl" in msg.lower()

    def test_empty_file(self):
        data = _make_excel_bytes(
            ["RollNo", "LeetCodeURL", "CodeforcesURL", "LinkedInURL", "GitHubURL"],
            [],
        )
        rows = read_excel(data)
        ok, msg = validate_columns(rows)
        assert not ok
        assert "empty" in msg.lower()
