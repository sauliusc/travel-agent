"""Food & Bars agent: cheap local eateries on the route, regional dishes with
price and verified photo, and genuinely special bars."""

from pathlib import Path

from agents.base import run_structured
from schemas.food import Bar, Dish, Eatery, FoodGuide, FoodGuideDraft, MustTry
from schemas.images import FoundImage, ImageResults
from tools.image_download import download_images
from tools.maps_links import place_search_url

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "food.md").read_text()
TIMEOUT = 1200


def guide(requirements_json: str, itinerary_json: str, accommodation: str) -> FoodGuide:
    draft = run_structured(
        SYSTEM_PROMPT, ["WebSearch", "WebFetch", "Bash"],
        f"Trip requirements:\n{requirements_json}\n\nItinerary:\n{itinerary_json}\n\n"
        f"Accommodation:\n{accommodation}",
        FoodGuideDraft, timeout=TIMEOUT,
    )

    # Dish photos (regional dishes and each eatery's must-try dishes) go
    # through the same download + license check as stop photos -- once per file.
    wanted: dict[str, str] = {}  # commons file -> name of the first dish using it
    for name, fn in [(d.name, d.commons_filename) for d in draft.dishes] + \
                    [(m.name, m.commons_filename) for e in draft.eateries for m in e.must_try]:
        if fn.strip():
            wanted.setdefault(fn.strip(), name)
    picks = ImageResults(images=[
        FoundImage(stop_name=name, local_path="images/dish.jpg", commons_filename=fn, license="?")
        for fn, name in wanted.items()
    ])
    by_name = {img.stop_name: img for img in download_images(picks).images} if picks.images else {}
    photo = {fn: by_name.get(name) for fn, name in wanted.items()}

    dishes = [Dish(**d.model_dump(), image=photo.get(d.commons_filename.strip())) for d in draft.dishes]
    # A must-try dish without its own photo borrows the regional dish's one.
    regional = {n.casefold(): d.image for d in dishes if d.image for n in (d.name, d.local_name) if n}

    def must_try(m) -> MustTry:
        image = photo.get(m.commons_filename.strip()) or regional.get(m.name.casefold()) \
            or regional.get(m.local_name.casefold())
        return MustTry(**m.model_dump(), image=image)

    return FoodGuide(
        eateries=[Eatery(**e.model_dump(exclude={"must_try"}), must_try=[must_try(m) for m in e.must_try],
                         maps_url=place_search_url(e.name, e.city, e.address)) for e in draft.eateries],
        dishes=dishes,
        bars=[Bar(**b.model_dump(), maps_url=place_search_url(b.name, b.city, b.address)) for b in draft.bars],
    )
