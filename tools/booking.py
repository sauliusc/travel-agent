"""Booking.com property details + photos for the place the travellers stay.

Run by code (not an LLM): the agents' WebFetch can't open booking.com, so the
page is fetched here with a browser-like request, falling back to headless
Chromium (Playwright) if installed and the plain request gets a bot check.
Details come from the page's own structured data (JSON-LD / OpenGraph);
photos are the property's gallery images, saved into the image cache so
CI/CD ships them with the page.

CLI: `python3 tools/booking.py --url https://www.booking.com/hotel/dk/....html`
"""

import argparse
import html as htmllib
import json
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from schemas.images import FoundImage  # noqa: E402
from tools.image_download import _image_kind, _slug, cache_path  # noqa: E402

BOOKING_URL = re.compile(r"https?://(?:www\.)?booking\.com/hotel/[^\s\"'<>)]+?\.html", re.I)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
MAX_PHOTOS = 5
_PHOTO = re.compile(r"https://cf\.bstatic\.com/xdata/images/hotel/[a-z0-9_]+/(\d+)\.jpg[^\"'\s<>\\]*", re.I)
_LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
_LODGING = {"hotel", "lodgingbusiness", "apartment", "accommodation", "hostel", "resort",
            "bedandbreakfast", "vacationrental", "house"}

_cache: dict[str, dict] = {}


def find_urls(*texts: str | None) -> list[str]:
    """booking.com property links in the given texts, query strings dropped, in order."""
    seen = []
    for text in texts:
        for m in BOOKING_URL.finditer(text or ""):
            url = m.group(0).split("?")[0]
            if url not in seen:
                seen.append(url)
    return seen


def _looks_like_property(page: str) -> bool:
    return "application/ld+json" in page and ("bstatic.com/xdata/images/hotel" in page or 'og:title' in page)


def _fetch_html(url: str) -> str:
    resp = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
    if resp.status_code == 200 and _looks_like_property(resp.text):
        return resp.text
    # Bot check / JS challenge: try a real browser if available.
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(f"booking.com returned HTTP {resp.status_code} without property data "
                           "(bot check), and Playwright isn't installed for a browser fallback")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=HEADERS["User-Agent"], locale="en-GB")
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            # The bot check runs JS and then reloads into the real page.
            try:
                page.wait_for_selector('script[type="application/ld+json"]', state="attached", timeout=25000)
            except Exception:  # noqa: BLE001 - judged below by the content
                pass
            text = page.content()
        finally:
            browser.close()
    if not _looks_like_property(text):
        raise RuntimeError("booking.com page has no property data even in a browser (bot check)")
    return text


def _meta(page: str, prop: str) -> str | None:
    m = re.search(rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"', page, re.I) \
        or re.search(rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{re.escape(prop)}"', page, re.I)
    return htmllib.unescape(m.group(1)).strip() if m else None


def _lodging_ld(page: str) -> dict:
    for block in _LD.findall(page):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]):
            types = item.get("@type", [])
            types = [types] if isinstance(types, str) else types
            if any(t.lower() in _LODGING for t in types):
                return item
    return {}


def parse(page: str, url: str) -> dict:
    """Property details from a booking.com page (no network)."""
    ld = _lodging_ld(page)
    addr = ld.get("address") or {}
    if isinstance(addr, dict):
        address = ", ".join(str(addr[k]) for k in ("streetAddress", "postalCode", "addressLocality",
                                                    "addressCountry") if addr.get(k))
    else:
        address = str(addr)
    rating = ld.get("aggregateRating") or {}
    photos, ids = [], set()
    for m in _PHOTO.finditer(page):
        if m.group(1) in ids:
            continue
        ids.add(m.group(1))
        photos.append(re.sub(r"/images/hotel/[a-z0-9_]+/", "/images/hotel/max1024x768/", m.group(0)).replace("&amp;", "&"))
        if len(photos) == MAX_PHOTOS:
            break
    if not photos and _meta(page, "og:image"):
        photos.append(_meta(page, "og:image"))
    return {
        "url": url,
        "name": ld.get("name") or _meta(page, "og:title"),
        "address": address or None,
        "description": htmllib.unescape(ld.get("description") or _meta(page, "og:description") or "").strip() or None,
        "rating": rating.get("ratingValue"),
        "rating_scale": rating.get("bestRating", 10) if rating else None,
        "review_count": rating.get("reviewCount"),
        "photo_urls": photos,
    }


def _download_photos(details: dict) -> list[FoundImage]:
    out = []
    base = _slug(details.get("name") or "stay")
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for i, src in enumerate(details["photo_urls"], 1):
            try:
                resp = client.get(src)
                resp.raise_for_status()
            except httpx.HTTPError:
                continue
            kind = _image_kind(resp.content)
            if kind is None:
                continue
            local_path = f"images/stay-{base}-{i}.{kind}"
            path = cache_path(local_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(resp.content)
            out.append(FoundImage(
                stop_name=details.get("name") or "Nakvynė", local_path=local_path, commons_filename="",
                license="© apgyvendinimo įstaiga / Booking.com", author=None, source_url=details["url"],
                size_bytes=len(resp.content),
            ))
    return out


def stay_details(url: str) -> dict:
    """Details + downloaded photos for one property; {"url", "error"} if the page can't be read."""
    if url in _cache:
        return _cache[url]
    try:
        details = parse(_fetch_html(url), url)
        details["photos"] = [p.model_dump() for p in _download_photos(details)]
    except Exception as e:  # noqa: BLE001 - reported to the agent/page, never fatal
        # Not cached: a rerun of the step should try the page again.
        return {"url": url, "error": str(e)}
    _cache[url] = details
    return details


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    print(json.dumps(stay_details(args.url), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
