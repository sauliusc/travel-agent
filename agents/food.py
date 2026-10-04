"""Food & Bars agent: cheap local eateries on the route, regional dishes with
price and verified photo, and genuinely special bars."""

from pathlib import Path

from agents.base import run_structured
from schemas.food import Bar, Dish, Eatery, FoodGuide, FoodGuideDraft
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

    # Dish photos go through the same download + license check as stop photos.
    picks = ImageResults(images=[
        FoundImage(stop_name=d.name, local_path="images/dish.jpg", commons_filename=d.commons_filename, license="?")
        for d in draft.dishes if d.commons_filename.strip()
    ])
    verified = {img.stop_name: img for img in download_images(picks).images} if picks.images else {}

    return FoodGuide(
        eateries=[Eatery(**e.model_dump(), maps_url=place_search_url(e.name, e.city)) for e in draft.eateries],
        dishes=[Dish(**d.model_dump(), image=verified.get(d.name)) for d in draft.dishes],
        bars=[Bar(**b.model_dump(), maps_url=place_search_url(b.name, b.city)) for b in draft.bars],
    )
