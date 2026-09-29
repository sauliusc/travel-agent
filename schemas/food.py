"""Food & bars agent output: cheap local eateries along the route, regional
dishes (with price and a verified photo), and genuinely special bars."""

from pydantic import BaseModel, Field

from schemas.images import FoundImage


class Eatery(BaseModel):
    name: str
    city: str
    day: int = Field(description="itinerary day it fits")
    near: str = Field(description="the itinerary stop or overnight place it is next to")
    kind: str = Field(description="e.g. 'šeimos taverna', 'byrektorė', 'turgus'")
    local_cuisine: bool = Field(description="true for places serving traditional local food")
    avg_price_eur: int = Field(description="typical price per person for a main dish + drink")
    rating: float | None = Field(default=None, description="0-5 scale, if known")
    review_source: str | None = None
    why: str = Field(description="one sentence for travellers, in the trip's language")
    maps_url: str = Field(default="", description="leave empty -- filled in by code")


class Dish(BaseModel):
    name: str = Field(description="name in the trip's language")
    local_name: str
    description: str = Field(description="one or two sentences, in the trip's language")
    price_eur_min: int
    price_eur_max: int
    where_to_try: list[str] = Field(description="names of eateries from the `eateries` list")
    commons_filename: str | None = Field(
        default=None, description="Wikimedia Commons file title of a photo of this dish, without 'File:'")
    image: FoundImage | None = Field(default=None, description="leave empty -- filled in by the download step")


class Bar(BaseModel):
    name: str
    city: str
    day: int
    near: str
    why_special: str = Field(description="what makes it worth visiting, in the trip's language")
    maps_url: str = Field(default="", description="leave empty -- filled in by code")


class FoodGuide(BaseModel):
    eateries: list[Eatery]
    dishes: list[Dish]
    bars: list[Bar] = Field(default_factory=list, description="only genuinely special bars; empty is fine")
