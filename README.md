# Placement Profile Enricher API

A focused Flask utility that turns a messy spreadsheet of profile links (LeetCode, Codeforces, LinkedIn, GitHub) into an actionable shortlist — automatically pulling contest ranks, ratings, profile photos, and recent GitHub activity.

## Features

- **Built-in Web Frontend** – clean drag-and-drop upload page at `http://localhost:5000` — no Postman or curl needed
- **Single API endpoint** – `POST /enrich` accepts an Excel file and returns a ZIP with enriched results + summary
- **Four platform scrapers** – LeetCode global contest rank, Codeforces current rating, LinkedIn profile photo, GitHub last-12-month contributions & public repos
- **Rate-limited & resilient** – token-bucket scheduler per platform with configurable delays, 2 retries with exponential back-off, failures isolated per row/platform
- **Efficient Excel handling** – Pandas for small/medium files; openpyxl streaming for large files (>5 MB or >10k cells) to keep memory under 300 MB
- **Auto-fitted columns** – enriched Excel output auto-sizes all column widths so headers like `GH_Public_Repos` are always fully visible
- **LinkedIn photo saving** – downloads profile photos to `photos/{rollno}.jpg` via Pillow for ID card workflows; photos are bundled inside the output ZIP
- **Structured logging** – every scrape attempt, retry, and error logged (console + `Enrich_Logs` Excel sheet)

## Quick Start

### 1. Set up virtual environment

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
# Edit .env as needed (e.g. set SELENIUM_ENABLED=true for LinkedIn)
```

### 4. Run the server

```bash
python app.py
```

The server starts at `http://localhost:5000`.

### 5. Open the frontend

Navigate to **http://localhost:5000** in your browser. You'll see:

1. A **column format guide** showing the required Excel layout
2. A **drag-and-drop upload area** — click or drop your `.xlsx` file
3. An **"Enrich Profiles"** button that kicks off processing
4. A **loading spinner** while the backend scrapes all platforms
5. **Automatic download** of `enriched_results.zip` when done

> **No external tools required.** The frontend is served directly by Flask — just open the URL and upload your file.

### Alternative: Using curl

```bash
curl -X POST \
  -F "excel=@candidates.xlsx" \
  http://localhost:5000/enrich \
  --output enriched_results.zip
```

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
- Five new columns appended (auto-fitted for readability):
  - `LC_Global_Contest_Rank` – LeetCode global contest rank (or `N/A`)
  - `CF_Rating` – Codeforces current rating (or `N/A`)
  - `Photos_Path` – relative path to saved photo, e.g. `photos/2021001.jpg` (or `N/A`)
  - `GH_Commits_12mo` – GitHub contributions in the last 12 months (or `N/A`)
  - `GH_Public_Repos` – total public GitHub repositories (or `N/A`)
- Additional sheet `Enrich_Logs` with columns: `timestamp`, `row_id`, `platform`, `url`, `status`, `message`

### `photos/` folder

- Contains downloaded LinkedIn profile photos as `{rollno}.jpg`
- Only present when photos were successfully retrieved

### `summary.json`

```json
{
  "total_rows": 50,
  "total_duration_ms": 62000,
  "overall_success_rate": 0.87,
  "platforms": {
    "leetcode": { "success_rate": 0.96, "error_count": 2 },
    "codeforces": { "success_rate": 0.98, "error_count": 1 },
    "linkedin": { "success_rate": 0.6, "error_count": 20 },
    "github": { "success_rate": 0.94, "error_count": 3 }
  }
}
```

## Performance Notes

| Rows | Estimated Time | Notes                                          |
| ---- | -------------- | ---------------------------------------------- |
| 10   | ~1–2 minutes   | ~3 min with Selenium enabled for LinkedIn      |
| 50   | ~5–6 minutes   | Sweet spot for quick batches                   |
| 150  | ~10 minutes    | Rate limiter ensures no platform gets hammered |

- Streaming mode activates automatically for files >5 MB or >10k cells to keep memory under 300 MB
- LinkedIn scraping has the lowest success rate due to aggressive bot detection — enable Selenium (`SELENIUM_ENABLED=true`) for better results
- GitHub contributions are fetched from the contributions calendar endpoint (no auth token required)

## Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

15 tests across three files cover the key scenarios:

- `test_column_mapping.py` – case-insensitive column detection, RollNo fallback, extra columns preserved
- `test_happy_path.py` – end-to-end success: all 4 scrapers return valid data, enriched output verified
- `test_failure_row.py` – all scrapers fail: N/A values, Enrich_Logs populated, job not aborted

## Project Structure

```
placement-enricher/
├── app.py                   # Flask entry point – GET / (frontend) + POST /enrich (API)
├── config.py                # All configurable constants (env vars)
├── rate_limiter.py          # Token-bucket rate limiter (per platform)
├── scheduler.py             # Round-robin row processor
├── scrapers/
│   ├── __init__.py
│   ├── leetcode.py          # LeetCode GraphQL scraper
│   ├── codeforces.py        # Codeforces HTML + API scraper
│   ├── linkedin.py          # LinkedIn photo scraper (BS4 + optional Selenium)
│   └── github.py            # GitHub contributions + repos scraper
├── excel_handler.py         # Read/write Excel (Pandas + openpyxl) with auto-fit columns
├── photo_handler.py         # Download & save images via Pillow
├── utils.py                 # URL validation, username extraction, retry wrapper
├── templates/
│   └── index.html           # Web frontend – drag-and-drop upload page
├── tests/
│   ├── test_column_mapping.py
│   ├── test_happy_path.py
│   └── test_failure_row.py
├── photos/                  # Saved LinkedIn profile photos (included in output ZIP)
├── requirements.txt
├── .env.example
└── README.md
```

## License

This project was built as a placement utility. Use it responsibly and respect each platform's terms of service.
