# Placement Profile Enricher API

A focused Flask utility that turns a messy spreadsheet of profile links (LeetCode, Codeforces, LinkedIn, GitHub) into an actionable shortlist — automatically pulling contest ranks, ratings, profile photos, and recent GitHub activity.

## Features

- **Single endpoint** – `POST /enrich` accepts an Excel file and returns a ZIP with enriched results + summary
- **Four platform scrapers** – LeetCode global contest rank, Codeforces current rating, LinkedIn profile photo, GitHub last-12-month contributions & public repos
- **Rate-limited & resilient** – token-bucket scheduler per platform with configurable delays, 2 retries with exponential back-off, failures isolated per row/platform
- **Efficient Excel handling** – Pandas for small/medium files; openpyxl streaming for large files (>5 MB or >10k cells) to keep memory under 300 MB
- **LinkedIn photo saving** – downloads profile photos to `photos/{rollno}.jpg` via Pillow for ID card workflows
- **Structured logging** – every scrape attempt, retry, and error logged (console + `Enrich_Logs` Excel sheet)

## Quick Start

### 1. Setup virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables (optional)

```bash
cp .env.example .env
# Edit .env as needed
```

### 4. Run the server

```bash
python app.py
```

The API will be available at `http://localhost:5000`.

## Environment Variables

| Variable                     | Default                                           | Description                                     |
| ---------------------------- | ------------------------------------------------- | ----------------------------------------------- |
| `RATE_LIMITS`                | `leetcode:1,codeforces:0.5,linkedin:0.3,github:1` | Per-platform token-bucket rates (tokens/second) |
| `REQUEST_TIMEOUT`            | `15`                                              | Network timeout per request (seconds)           |
| `SELENIUM_ENABLED`           | `false`                                           | Enable Selenium for LinkedIn dynamic images     |
| `MAX_FILE_SIZE`              | `10485760`                                        | Max upload size in bytes (default 10 MB)        |
| `LARGE_FILE_THRESHOLD_BYTES` | `5242880`                                         | Switch to streaming mode above this (5 MB)      |
| `LARGE_FILE_THRESHOLD_CELLS` | `10000`                                           | Switch to streaming mode above this many cells  |
| `INTER_REQUEST_DELAY_MIN`    | `750`                                             | Minimum inter-request delay (ms)                |
| `INTER_REQUEST_DELAY_MAX`    | `1250`                                            | Maximum inter-request delay (ms)                |
| `MAX_RETRIES`                | `2`                                               | Retries per platform fetch                      |
| `BACKOFF_BASE`               | `2`                                               | Exponential back-off base (seconds)             |
| `PHOTOS_DIR`                 | `./photos`                                        | Directory for saved LinkedIn profile photos     |

## Usage

### Example curl command

```bash
curl -X POST \
  -F "excel=@candidates.xlsx" \
  http://localhost:5000/enrich \
  --output enriched_results.zip
```

### Example HTML form

```html
<form
  action="http://localhost:5000/enrich"
  method="post"
  enctype="multipart/form-data"
>
  <input type="file" name="excel" accept=".xlsx" />
  <button type="submit">Enrich</button>
</form>
```

## Input Excel Format

The uploaded `.xlsx` file must contain these column headers (case-insensitive):

| Column          | Required      | Description                                  |
| --------------- | ------------- | -------------------------------------------- |
| `RollNo`        | Recommended\* | Unique identifier for each candidate         |
| `LeetCodeURL`   | Yes           | e.g. `https://leetcode.com/u/username`       |
| `CodeforcesURL` | Yes           | e.g. `https://codeforces.com/profile/handle` |
| `LinkedInURL`   | Yes           | e.g. `https://www.linkedin.com/in/username`  |
| `GitHubURL`     | Yes           | e.g. `https://github.com/username`           |

\* If `RollNo` is missing, an identifier is derived from the GitHub or LinkedIn username.

## Output

The response is a ZIP file (`enriched_results.zip`) containing:

### `enriched.xlsx`

- All original columns preserved
- Five new columns appended:
  - `LC_Global_Contest_Rank` – LeetCode global contest rank (or `N/A`)
  - `CF_Rating` – Codeforces current rating (or `N/A`)
  - `Photos_Path` – relative path to saved photo, e.g. `photos/2021001.jpg` (or `N/A`)
  - `GH_Commits_12mo` – GitHub contributions in the last 12 months (or `N/A`)
  - `GH_Public_Repos` – total public GitHub repositories (or `N/A`)
- Additional sheet `Enrich_Logs` with columns: `timestamp`, `row_id`, `platform`, `url`, `status`, `message`

### `summary.json`

```json
{
  "total_rows": 50,
  "total_duration_ms": 62000,
  "overall_success_rate": 0.87,
  "platforms": {
    "leetcode": {
      "success_rate": 0.96,
      "error_count": 2,
      "sample_errors": ["Row 12: User has not participated in any contest"]
    },
    "codeforces": {
      "success_rate": 0.98,
      "error_count": 1,
      "sample_errors": []
    },
    "linkedin": {
      "success_rate": 0.6,
      "error_count": 20,
      "sample_errors": ["Row 3: LinkedIn blocked the request"]
    },
    "github": {
      "success_rate": 0.94,
      "error_count": 3,
      "sample_errors": ["Row 7: Could not parse contributions from profile"]
    }
  }
}
```

## Performance Notes

- For ~150 rows: expect ~10 minutes total (4 platforms × 150 rows × ~1 s average delay per request)
- Streaming mode activates automatically for files >5 MB or >10k cells to keep memory under 300 MB
- LinkedIn scraping has the lowest success rate due to aggressive bot detection (HTTP 999)
- GitHub "contributions" includes commits + PRs + issues + reviews (pure commit-only count requires an auth token which this tool intentionally avoids per the no-credentials requirement)

## Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

Three test files cover the PRD's required test scenarios:

- `test_column_mapping.py` – case-insensitive column detection, RollNo fallback, extra columns preserved
- `test_happy_path.py` – end-to-end success: all 4 scrapers return valid data, enriched output verified
- `test_failure_row.py` – all scrapers fail: N/A values, Enrich_Logs populated, job not aborted

## Project Structure

```
placement-enricher/
├── app.py                  # Flask entry point + POST /enrich
├── config.py               # All configurable constants (env vars)
├── rate_limiter.py          # Token-bucket rate limiter (per platform)
├── scheduler.py             # Round-robin row processor
├── scrapers/
│   ├── __init__.py
│   ├── leetcode.py          # LeetCode GraphQL scraper
│   ├── codeforces.py        # Codeforces HTML + API scraper
│   ├── linkedin.py          # LinkedIn photo scraper (BS4 + optional Selenium)
│   └── github.py            # GitHub contributions + repos scraper
├── excel_handler.py         # Read/write Excel (Pandas + openpyxl)
├── photo_handler.py         # Download & save images via Pillow
├── utils.py                 # URL validation, username extraction, retry wrapper
├── tests/
│   ├── test_column_mapping.py
│   ├── test_happy_path.py
│   └── test_failure_row.py
├── photos/                  # Saved LinkedIn profile photos
├── requirements.txt
├── .env.example
└── README.md
```
