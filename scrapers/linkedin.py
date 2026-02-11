"""
LinkedIn scraper – fetch profile photo.
PRD §4 FR: fetch profile photo, save to /photos/{rollno}.jpg; column Photos_Path.
PRD §2: Selenium (optional) with headless Chrome/Firefox for dynamic LinkedIn images.

Primary path: requests + BeautifulSoup (og:image meta tag).
Optional path: Selenium (when SELENIUM_ENABLED=true).
"""

import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, SELENIUM_ENABLED
from utils import validate_and_sanitize_url, BROWSER_HEADERS
from photo_handler import download_and_save

logger = logging.getLogger(__name__)


def _fetch_photo_bs4(url: str) -> str | None:
    """Attempt to get the profile photo URL using requests + BeautifulSoup."""
    headers = {
        **BROWSER_HEADERS,
        "Accept-Language": "en-US,en;q=0.9",
    }

    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)

    # LinkedIn returns HTTP 999 for detected bots
    if resp.status_code == 999:
        logger.warning("LinkedIn returned 999 (bot detection) for %s", url)
        return None

    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Strategy 1: og:image meta tag (most reliable)
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        img_url = og_img["content"]
        if "licdn.com" in img_url or "linkedin.com" in img_url:
            return img_url

    # Strategy 2: direct img tag with profile photo URL
    img_tag = soup.find("img", src=lambda s: s and "profile-displayphoto" in s)
    if img_tag and img_tag.get("src"):
        return img_tag["src"]

    # Strategy 3: scan all img tags for licdn media URLs
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "media.licdn.com" in src and "profile" in src:
            return src

    return None


def _fetch_photo_selenium(url: str) -> str | None:
    """Optional Selenium path for dynamic LinkedIn content.

    Only activated when SELENIUM_ENABLED=true.
    Launches a headless Chrome browser that renders JavaScript and
    searches for any profile-photo ``<img>`` element on the page.
    """
    try:
        from selenium import webdriver  # type: ignore[import-untyped]
        from selenium.webdriver.chrome.options import Options  # type: ignore[import-untyped]
        from selenium.webdriver.common.by import By  # type: ignore[import-untyped]
        from selenium.webdriver.support.ui import WebDriverWait  # type: ignore[import-untyped]
        from selenium.webdriver.support import expected_conditions as EC  # type: ignore[import-untyped]
        import time as _time

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            f"user-agent={BROWSER_HEADERS['User-Agent']}"
        )
        # Suppress the "Chrome is being controlled by automated software" banner
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        driver = webdriver.Chrome(options=options)
        try:
            # Remove navigator.webdriver flag to avoid detection
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
            )
            driver.get(url)
            # Give LinkedIn JS time to render
            _time.sleep(3)

            # Broad set of CSS selectors — LinkedIn changes class names frequently
            selectors = [
                # Current (2024-2026) public profile selectors
                "img.pv-top-card-profile-picture__image--show",
                "img.pv-top-card-profile-picture__image",
                "img.profile-photo-edit__preview",
                "img.presence-entity__image",
                "img.EntityPhoto-circle-9",
                "img.EntityPhoto-circle-8",
                # Generic: any img whose src points to LinkedIn media
                "img[src*='media.licdn.com'][src*='profile-displayphoto']",
                "img[src*='media.licdn.com'][src*='profile']",
                # Fallback: og:image meta (some pages render it in JS)
            ]

            for sel in selectors:
                try:
                    imgs = driver.find_elements(By.CSS_SELECTOR, sel)
                    for img in imgs:
                        src = img.get_attribute("src") or ""
                        # Skip ghost/default avatar placeholders
                        if src and "licdn.com" in src and "ghost" not in src and "data:image" not in src:
                            logger.info("LinkedIn Selenium: found photo via selector %s", sel)
                            return src
                except Exception:
                    continue

            # Last resort: find any <img> whose src contains profile media
            all_imgs = driver.find_elements(By.TAG_NAME, "img")
            for img in all_imgs:
                src = img.get_attribute("src") or ""
                if "media.licdn.com" in src and "ghost" not in src and "data:image" not in src:
                    logger.info("LinkedIn Selenium: found photo via generic img scan")
                    return src

            logger.warning("LinkedIn Selenium: no profile photo found for %s", url)
            return None
        finally:
            driver.quit()
    except ImportError:
        logger.warning(
            "SELENIUM_ENABLED=true but selenium is not installed. "
            "Install with: pip install selenium"
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Selenium LinkedIn fetch failed: %s", exc)
        return None


def scrape_linkedin(url: str, rollno: str) -> dict:
    """Scrape LinkedIn profile photo for the given URL.

    Returns
    -------
    dict
        Keys: ``Photos_Path``, ``log`` (dict with log entry fields).
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": "linkedin",
        "url": url,
        "status": "error",
        "message": "",
    }

    sanitized = validate_and_sanitize_url(url, "linkedin")
    if not sanitized:
        log_entry["message"] = "Invalid or empty LinkedIn URL"
        logger.info("LinkedIn: %s", log_entry["message"])
        return {"Photos_Path": "N/A", "log": log_entry}

    logger.info("LinkedIn: fetching profile photo for %s", rollno)

    photo_url = None

    # Try Selenium first if enabled (PRD §2 optional path)
    if SELENIUM_ENABLED:
        logger.info("LinkedIn: attempting Selenium fetch for %s", rollno)
        photo_url = _fetch_photo_selenium(sanitized)

    # Primary path: BS4 (PRD §2 tech stack: BeautifulSoup4 + requests)
    if photo_url is None:
        photo_url = _fetch_photo_bs4(sanitized)

    if not photo_url:
        log_entry["message"] = "Profile photo not found or blocked by LinkedIn"
        logger.info("LinkedIn: %s – %s", rollno, log_entry["message"])
        return {"Photos_Path": "N/A", "log": log_entry}

    # Download and save photo using Pillow (PRD §3 Core Req #4)
    saved_path = download_and_save(photo_url, rollno)
    if not saved_path:
        log_entry["message"] = "Failed to download or save profile photo"
        logger.info("LinkedIn: %s – %s", rollno, log_entry["message"])
        return {"Photos_Path": "N/A", "log": log_entry}

    log_entry["status"] = "success"
    log_entry["message"] = f"Photo saved to {saved_path}"
    logger.info("LinkedIn: %s – photo saved to %s", rollno, saved_path)
    return {"Photos_Path": saved_path, "log": log_entry}
