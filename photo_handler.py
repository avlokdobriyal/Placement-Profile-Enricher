"""
Photo handler – download and save LinkedIn profile photos using Pillow.
PRD §3 Core Req #4: download and save to /photos/{rollno}.jpg using Pillow;
                     persist relative path into the Excel output.
PRD §5 NFR: photos are intentionally persisted on disk (for ID cards).
"""

import os
import logging
from io import BytesIO

import requests
from PIL import Image

from config import PHOTOS_DIR, REQUEST_TIMEOUT
from utils import BROWSER_HEADERS

logger = logging.getLogger(__name__)


def download_and_save(photo_url: str, rollno: str) -> str | None:
    """Download a profile photo and save as ``photos/{rollno}.jpg``.

    Parameters
    ----------
    photo_url : str
        Direct URL to the image.
    rollno : str
        Roll number (or derived identifier) used as the filename.

    Returns
    -------
    str | None
        Relative path ``photos/{rollno}.jpg`` on success, *None* on failure.
    """
    try:
        os.makedirs(PHOTOS_DIR, exist_ok=True)

        logger.info("Photo: downloading image for %s", rollno)
        resp = requests.get(
            photo_url, headers=BROWSER_HEADERS, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()

        # Verify the response is actually an image (not an HTML redirect page)
        content_type = resp.headers.get("Content-Type", "")
        if "image" not in content_type and len(resp.content) < 100:
            logger.warning("Photo: response for %s is not an image (Content-Type: %s)", rollno, content_type)
            return None

        img = Image.open(BytesIO(resp.content))

        # Convert RGBA / palette / other modes to RGB for JPEG
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")

        filename = f"{rollno}.jpg"
        filepath = os.path.join(PHOTOS_DIR, filename)
        img.save(filepath, "JPEG", quality=85)

        # Return the relative path that goes into Photos_Path column
        relative = f"photos/{filename}"
        logger.info("Photo: saved %s", relative)
        return relative

    except Exception as exc:  # noqa: BLE001
        logger.error("Photo: failed to save for %s – %s", rollno, exc)
        return None
