"""Photo lookup for a trip spot via the Wikimedia Commons API (free, open license)."""

import httpx
from anthropic import beta_tool

SEARCH_URL = "https://commons.wikimedia.org/w/api.php"
UA = "travel-agent/1.0 (https://github.com/sauliusc/travel-agent; saulius@cebanauskai.lt)"


@beta_tool
def find_image(query: str, min_width: int = 640) -> str:
    """Search Wikimedia Commons for a photo matching a place or landmark name.

    Args:
        query: place or landmark name to search for, e.g. "Gjirokaster castle"
        min_width: minimum thumbnail width in pixels to request (default 640)
    """
    headers = {"User-Agent": UA}

    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": f"{query} filetype:bitmap",
        "srnamespace": 6,  # File namespace
        "srlimit": 1,
        "format": "json",
    }
    with httpx.Client(headers=headers, timeout=30) as client:
        search_resp = client.get(SEARCH_URL, params=search_params)
        search_resp.raise_for_status()
        results = search_resp.json().get("query", {}).get("search", [])
        if not results:
            return f"No Wikimedia Commons image found for '{query}'"

        title = results[0]["title"]  # e.g. "File:Gjirokastren me Kalane e saj.jpg"

        info_params = {
            "action": "query",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": min_width,
            "titles": title,
            "format": "json",
        }
        info_resp = client.get(SEARCH_URL, params=info_params)
        info_resp.raise_for_status()
        pages = info_resp.json()["query"]["pages"]
        page = next(iter(pages.values()))
        imageinfo = page.get("imageinfo")
        if not imageinfo:
            return f"Found '{title}' but could not retrieve image info"

        info = imageinfo[0]
        thumb_url = info.get("thumburl", info.get("url"))
        license_name = info.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "unknown")

        return (
            f"title={title} thumb_url={thumb_url} license={license_name} "
            f"page_url=https://commons.wikimedia.org/wiki/{title.replace(' ', '_')}"
        )
