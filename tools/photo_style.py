"""Fixed photo styles, injected by code into every generated page.

The Page Designer writes its own CSS, and each run sized the place photos
differently (sometimes tiny thumbnails). These rules come last in <head> and
use !important, so photos look the same on every run whatever the
designer's CSS says:

- `img.spot-thumb` -- a place photo: full width of its card, large.
- `.photo-grid` -- a gallery (accommodation photos): large tiles side by side.
- `img.dish-thumb` -- a dish photo (regional dishes, an eatery's must-try
  dishes): a medium tile in a `.dish-grid`.
"""

START, END = "<!-- PHOTO_STYLE:START -->", "<!-- PHOTO_STYLE:END -->"

STYLE = """<style>
img.spot-thumb{display:block!important;width:100%!important;max-width:100%!important;height:auto!important;
  aspect-ratio:3/2!important;object-fit:cover!important;border-radius:12px!important;margin:10px 0!important;cursor:zoom-in}
.photo-grid{display:grid!important;grid-template-columns:repeat(auto-fill,minmax(280px,1fr))!important;gap:10px!important;margin:10px 0!important}
.photo-grid img.spot-thumb{margin:0!important}
.dish-grid{display:grid!important;grid-template-columns:repeat(auto-fill,minmax(170px,1fr))!important;gap:10px!important;margin:10px 0!important}
.dish-grid figure{margin:0!important}
img.dish-thumb{display:block!important;width:100%!important;max-width:100%!important;height:auto!important;
  aspect-ratio:4/3!important;object-fit:cover!important;border-radius:10px!important;cursor:zoom-in}
.dish-grid figcaption{font-size:.9em;margin-top:4px}
@media(max-width:600px){.photo-grid{grid-template-columns:1fr!important}.dish-grid{grid-template-columns:repeat(2,1fr)!important}}
</style>"""


def inject(page_html: str) -> str:
    """Add the photo styles at the end of <head> (replacing an earlier copy)."""
    page_html = strip(page_html)
    block = START + STYLE + END
    idx = page_html.lower().find("</head>")
    return page_html[:idx] + block + page_html[idx:] if idx != -1 else block + page_html


def strip(page_html: str) -> str:
    """The page without the injected styles (for incremental page updates)."""
    a, b = page_html.find(START), page_html.find(END)
    if a == -1 or b == -1:
        return page_html
    return page_html[:a] + page_html[b + len(END):]
