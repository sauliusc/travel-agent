"""Food & bars: cheap local eateries along the route, regional dishes (with
price and a verified photo), and genuinely special bars.

Two layers: the *Draft models are what the agent fills via --json-schema;
the final models add the fields code fills in afterwards (Maps links, verified
photo). Keeping code-filled fields -- especially the nested optional image
object -- out of the agent's schema matters: with them in it, a real run
failed 5 structured-output attempts in a row.
"""

from pydantic import BaseModel, Field

from schemas.images import FoundImage


class EateryDraft(BaseModel):
    name: str
    city: str
    day: int = Field(description="itinerary day it fits")
    near: str = Field(description="the itinerary stop or overnight place it is next to")
    kind: str = Field(description="e.g. 'šeimos taverna', 'byrektorė', 'turgus'")
    local_cuisine: bool = Field(description="true for places serving traditional local food")
    avg_price_eur: int = Field(description="typical price per person for a main dish + drink")
    why: str = Field(description="one sentence for travellers, in the trip's language")


class DishDraft(BaseModel):
    name: str = Field(description="name in the trip's language")
    local_name: str
    description: str = Field(description="one or two sentences, in the trip's language")
    price_eur_min: int
    price_eur_max: int
    where_to_try: list[str] = Field(description="names of eateries from the `eateries` list")
    commons_filename: str = Field(
        description="Wikimedia Commons file title of a photo of this dish, without 'File:'; "
        "empty string if none found")


class BarDraft(BaseModel):
    name: str
    city: str
    day: int
    near: str
    why_special: str = Field(description="what makes it worth visiting, in the trip's language")


class FoodGuideDraft(BaseModel):
    eateries: list[EateryDraft]
    dishes: list[DishDraft]
    bars: list[BarDraft] = Field(description="only genuinely special bars; empty list is fine")


class Eatery(EateryDraft):
    maps_url: str


class Dish(DishDraft):
    image: FoundImage | None = None


class Bar(BarDraft):
    maps_url: str


class FoodGuide(BaseModel):
    eateries: list[Eatery]
    dishes: list[Dish]
    bars: list[Bar] = Field(default_factory=list)
