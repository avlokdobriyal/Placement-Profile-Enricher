"""
Placement Profile Enricher API – Flask application.
PRD §3 Core Req #1: POST /enrich – accept multipart/form-data (Excel .xlsx),
                     return enriched result + JSON summary in a single ZIP.
PRD §4 FR: file field "excel"; validate type, size, columns.
PRD §5 NFR: 10 MB limit, MIME restriction, uploads not stored beyond request scope.
PRD §1: "logs every step."
"""

import json
import logging
import os
import sys
import time
import zipfile
from io import BytesIO

from flask import Flask, Response, jsonify, render_template, request

from config import (
    MAX_FILE_SIZE,
    LARGE_FILE_THRESHOLD_BYTES,
    LARGE_FILE_THRESHOLD_CELLS,
    PLATFORMS,
    RATE_LIMITS,
)
from excel_handler import (
    read_excel,
    validate_columns,
    write_enriched,
    write_enriched_streaming,
    _needs_streaming,
)
from rate_limiter import build_rate_limiters
from scheduler import process_rows_round_robin

# ---------------------------------------------------------------------------
# Logging setup  (PRD §1: "logs every step")
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE  # 10 MB


ALLOWED_MIMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    # Some clients may send these:
    "application/octet-stream",
}

ALLOWED_EXTENSIONS = {".xlsx"}


@app.route("/")
def index():
    """Serve the frontend upload page."""
    return render_template("index.html")


@app.route("/enrich", methods=["POST"])
def enrich():
    """``POST /enrich`` – accept Excel, return enriched ZIP.

    PRD §4 FR: multipart/form-data with file field ``excel``.
    """
    logger.info("POST /enrich – request received")

    # ---- 1. Validate file presence ----
    if "excel" not in request.files:
        logger.warning("No file field 'excel' in request")
        return jsonify({"error": "Missing file field 'excel'"}), 400

    file = request.files["excel"]

    if not file or file.filename == "":
        logger.warning("Empty file uploaded")
        return jsonify({"error": "No file selected"}), 400

    # ---- 2. Validate extension (PRD §4 FR: .xlsx) ----
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        logger.warning("Invalid file extension: %s", ext)
        return jsonify({"error": f"Invalid file type '{ext}'. Only .xlsx is accepted"}), 400

    # ---- 3. Validate MIME type (PRD §5 NFR: restrict accepted MIME types) ----
    if file.mimetype not in ALLOWED_MIMES:
        logger.warning("Invalid MIME type: %s", file.mimetype)
        return (
            jsonify({"error": f"Invalid MIME type '{file.mimetype}'. Only .xlsx is accepted"}),
            400,
        )

    # ---- 4. Read file into memory (PRD §5 NFR: avoid storing uploads) ----
    file_bytes = file.read()
    logger.info("File received: %s (%d bytes)", file.filename, len(file_bytes))

    if len(file_bytes) > MAX_FILE_SIZE:
        logger.warning("File too large: %d bytes", len(file_bytes))
        return jsonify({"error": f"File exceeds {MAX_FILE_SIZE // (1024*1024)} MB limit"}), 400

    # ---- 5. Read Excel ----
    try:
        rows = read_excel(file_bytes)
    except Exception as exc:
        logger.error("Failed to read Excel: %s", exc)
        return jsonify({"error": f"Failed to read Excel file: {exc}"}), 400

    # ---- 6. Validate columns (PRD §4 FR: case-insensitive headers) ----
    ok, err_msg = validate_columns(rows)
    if not ok:
        logger.warning("Column validation failed: %s", err_msg)
        return jsonify({"error": err_msg}), 400

    total_rows = len(rows)
    logger.info("Excel parsed: %d rows", total_rows)

    # ---- 7. Initialise rate limiters (PRD §5 NFR: token-bucket per platform) ----
    rate_limiters = build_rate_limiters(RATE_LIMITS)

    # ---- 8. Process rows (PRD §6 User Flow #3–5) ----
    start_time = time.time()
    enriched_data, log_records, stats = process_rows_round_robin(rows, rate_limiters)
    total_duration_ms = int((time.time() - start_time) * 1000)

    logger.info("Processing complete in %d ms", total_duration_ms)

    # ---- 9. Write enriched Excel (PRD §4 FR) ----
    use_streaming = _needs_streaming(file_bytes)
    if use_streaming:
        excel_bytes = write_enriched_streaming(rows, enriched_data, log_records)
    else:
        excel_bytes = write_enriched(rows, enriched_data, log_records)

    logger.info("Enriched Excel: %d bytes", len(excel_bytes))

    # ---- 10. Build summary.json (PRD §4 FR) ----
    summary = _build_summary(total_rows, total_duration_ms, stats)
    summary_bytes = json.dumps(summary, indent=2, ensure_ascii=False).encode("utf-8")

    # ---- 11. Package into ZIP (PRD §3 Core Req #1) ----
    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("enriched.xlsx", excel_bytes)
        zf.writestr("summary.json", summary_bytes)

        # Include downloaded LinkedIn photos in photos/ folder
        photos_dir = os.path.join(os.path.dirname(__file__), "photos")
        if os.path.isdir(photos_dir):
            for fname in os.listdir(photos_dir):
                fpath = os.path.join(photos_dir, fname)
                if os.path.isfile(fpath) and fname.lower().endswith(".jpg"):
                    zf.write(fpath, f"photos/{fname}")

    zip_bytes = zip_buf.getvalue()
    logger.info("ZIP response: %d bytes", len(zip_bytes))

    # ---- 12. Return application/zip (PRD §4 FR) ----
    return Response(
        zip_bytes,
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=enriched_results.zip"},
    )


def _build_summary(total_rows: int, total_duration_ms: int, stats: dict) -> dict:
    """Build the summary.json structure per PRD §4 FR:

    - total_rows, total_duration_ms (top-level)
    - Per platform: success_rate, error_count, sample_errors
    - overall_success_rate (PRD §3 Core Req #5: "overall success rates")
    """
    platforms: dict = {}
    total_success = 0
    total_platform_attempts = 0

    for p in PLATFORMS:
        p_stats = stats.get(p, {})
        success = p_stats.get("success_count", 0)
        errors = p_stats.get("error_count", 0)
        attempts = success + errors

        total_success += success
        total_platform_attempts += attempts

        success_rate = round(success / attempts, 4) if attempts > 0 else 0.0

        # sample_errors: first 5 messages (PRD §4 FR: "sample_errors per platform")
        sample_errors = p_stats.get("error_messages", [])[:5]

        platforms[p] = {
            "success_rate": success_rate,
            "error_count": errors,
            "sample_errors": sample_errors,
        }

    overall_success_rate = (
        round(total_success / total_platform_attempts, 4)
        if total_platform_attempts > 0
        else 0.0
    )

    return {
        "total_rows": total_rows,
        "total_duration_ms": total_duration_ms,
        "overall_success_rate": overall_success_rate,
        "platforms": platforms,
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
