"""Deterministic download + verification of the Image agent's picks.

Runs in the pipeline right after the Image agent (not by an LLM): for each
pick it re-resolves the file via the Commons API, takes license and author
from Commons itself (not from the agent's claim), downloads a 1280px
thumbnail, and checks the bytes really are an image. Only images that pass
are kept, so the Page Designer and Critic see files that actually exist,
and CI/CD pushes them together with index.html.

CLI (smoke test): `python3 tools/image_download.py --title "Berat castle.jpg"`
"""

import argparse
import hashlib
import html
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))  # so the CLI form can import schemas/

from schemas.images import FoundImage, ImageResults

API_URL = "https://commons.wikimedia.org/w/api.php"
UA = "travel-agent/1.0 (https://github.com/sauliusc/travel-agent)"
THUMB_WIDTH = 1280
MAX_BYTES = 5_000_000

CACHE_DIR = Path(__file__).parent.parent / "image_cache"

ALLOWED_LICENSE_PREFIXES = ("cc by", "cc-by", "cc0", "public domain", "pd")

_MAGIC = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png", b"RIFF": "webp", b"GIF8": "gif"}


def _clean_title(name: str) -> str:
    title = unquote(name).strip()
    return title[5:] if title.lower().startswith("file:") else title


def _strip_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def _image_kind(data: bytes) -> str | None:
    for magic, kind in _MAGIC.items():
        if data.startswith(magic):
            return kind
    return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "image"


def cache_path(local_path: str) -> Path:
    """Where the bytes for a manifest entry's local_path live on disk."""
    return CACHE_DIR / Path(local_path).name


def resolve(title: str, client: httpx.Client) -> dict:
    resp = client.get(API_URL, params={
        "action": "query", "prop": "imageinfo", "iiprop": "url|extmetadata",
        "iiurlwidth": THUMB_WIDTH, "titles": f"File:{title}", "format": "json",
    })
    resp.raise_for_status()
    page = next(iter(resp.json()["query"]["pages"].values()))
    if "imageinfo" not in page:
        raise ValueError("file not found on Commons")
    info = page["imageinfo"][0]
    meta = info.get("extmetadata", {})
    return {
        "thumb_url": info.get("thumburl") or info["url"],
        "source_url": info.get("descriptionurl"),
        "license": _strip_html(meta.get("LicenseShortName", {}).get("value", "")),
        "author": _strip_html(meta.get("Artist", {}).get("value", "")) or None,
    }


def download_images(results: ImageResults) -> ImageResults:
    """Return a manifest of only the images that were really downloaded and are
    openly licensed; everything else goes to `skipped` with a reason."""
    CACHE_DIR.mkdir(exist_ok=True)
    kept: list[FoundImage] = []
    skipped: dict[str, str] = {}

    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        for img in results.images:
            title = _clean_title(img.commons_filename)
            try:
                info = resolve(title, client)
                if not info["license"].lower().startswith(ALLOWED_LICENSE_PREFIXES):
                    skipped[img.stop_name] = f"license not allowed: {info['license'] or 'unknown'}"
                    continue
                resp = client.get(info["thumb_url"])
                resp.raise_for_status()
                data = resp.content
                kind = _image_kind(data)
                if kind is None:
                    skipped[img.stop_name] = "downloaded file is not an image"
                    continue
                if len(data) > MAX_BYTES:
                    skipped[img.stop_name] = f"too large ({len(data):,} bytes)"
                    continue
            except Exception as e:  # noqa: BLE001 - one bad image must not fail the stage
                skipped[img.stop_name] = f"download failed: {e}"
                continue

            digest = hashlib.sha1(title.encode()).hexdigest()[:8]
            local_path = f"images/{_slug(img.stop_name)}-{digest}.{kind}"
            cache_path(local_path).write_bytes(data)
            kept.append(img.model_copy(update={
                "commons_filename": title,
                "local_path": local_path,
                "license": info["license"],
                "author": info["author"],
                "source_url": info["source_url"],
                "size_bytes": len(data),
            }))

    return ImageResults(images=kept, skipped=skipped)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="Commons file title")
    args = parser.parse_args()
    out = download_images(ImageResults(images=[FoundImage(
        stop_name="smoke", local_path="images/smoke.jpg",
        commons_filename=args.title, license="?",
    )]))
    print(out.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
