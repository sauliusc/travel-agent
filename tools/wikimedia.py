"""Photo lookup for a trip spot via the Wikimedia Commons API (free, open license).

Callable both as a Python function and as a CLI script, so the Image
agent (running under Claude Code) can invoke it via the Bash tool:
`python3 tools/wikimedia.py --query "Gjirokaster castle" [--min-width 640]`
"""

import argparse

import httpx

SEARCH_URL = "https://commons.wikimedia.org/w/api.php"
UA = "travel-agent/1.0 (https://github.com/sauliusc/travel-agent; saulius@cebanauskai.lt)"


def find_image(query: str, min_width: int = 640) -> str:
    """Search Wikimedia Commons for a photo matching a place or landmark name."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--min-width", type=int, default=640)
    args = parser.parse_args()
    print(find_image(args.query, args.min_width))


if __name__ == "__main__":
    main()
