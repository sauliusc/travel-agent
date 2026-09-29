"""Food & Bars agent: cheap local eateries on the route, regional dishes with
price and verified photo, and genuinely special bars."""

from pathlib import Path

from agents.base import run_structured
from schemas.food import FoodGuide
from schemas.images import FoundImage, ImageResults
from tools.image_download import download_images
from tools.maps_links import place_search_url

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "food.md").read_text()
TIMEOUT = 1200


def guide(requirements_json: str, itinerary_json: str, accommodation: str) -> FoodGuide:
    food = run_structured(
        SYSTEM_PROMPT, ["WebSearch", "WebFetch", "Bash"],
        f"Trip requirements:\n{requirements_json}\n\nItinerary:\n{itinerary_json}\n\n"
        f"Accommodation:\n{accommodation}",
        FoodGuide, timeout=TIMEOUT,
    )
    for place in [*food.eateries, *food.bars]:
        place.maps_url = place_search_url(place.name, place.city)

    # Dish photos go through the same download + license check as stop photos.
    picks = ImageResults(images=[
        FoundImage(stop_name=d.name, local_path="images/dish.jpg", commons_filename=d.commons_filename, license="?")
        for d in food.dishes if d.commons_filename
    ])
    verified = {img.stop_name: img for img in download_images(picks).images}
    for dish in food.dishes:
        dish.image = verified.get(dish.name)
    return food
