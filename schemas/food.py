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


class MustTryDraft(BaseModel):
    name: str = Field(description="dish name in the trip's language")
    local_name: str = Field(default="", description="as written on the local menu")
    price_eur: int = Field(description="typical price of this dish at this place")
    commons_filename: str = Field(
        description="Wikimedia Commons file title of a photo of this dish, without 'File:'; "
        "empty string if none found")


class EateryDraft(BaseModel):
    name: str
    city: str
    address: str = Field(default="", description="street address, so Google Maps finds this exact place "
                         "(needed when the name is shared by other places); empty if unknown")
    day: int = Field(description="itinerary day it fits")
    near: str = Field(description="the itinerary stop or overnight place it is next to")
    kind: str = Field(description="e.g. 'šeimos taverna', 'byrektorė', 'turgus'")
    local_cuisine: bool = Field(description="true for places serving traditional local food")
    avg_price_eur: int = Field(description="typical price per person for a main dish + drink")
    dinner_price_eur: int = Field(description="preliminary dinner price per person: a starter or salad, "
                                  "a main dish and a drink")
    must_try: list[MustTryDraft] = Field(min_length=3, description="at least 3 dishes worth trying here, "
                                         "the place's signature or local dishes first")
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
    address: str = Field(default="", description="street address, so Google Maps finds this exact place "
                         "(needed when the name is shared by other places); empty if unknown")
    day: int
    near: str
    why_special: str = Field(description="what makes it worth visiting, in the trip's language")


class FoodGuideDraft(BaseModel):
    eateries: list[EateryDraft]
    dishes: list[DishDraft]
    bars: list[BarDraft] = Field(description="only genuinely special bars; empty list is fine")


class MustTry(MustTryDraft):
    image: FoundImage | None = None


class Eatery(EateryDraft):
    maps_url: str
    must_try: list[MustTry] = Field(default_factory=list)
    dinner_price_eur: int | None = None  # absent in guides saved before it existed


class Dish(DishDraft):
    image: FoundImage | None = None


class Bar(BarDraft):
    maps_url: str


class FoodGuide(BaseModel):
    eateries: list[Eatery]
    dishes: list[Dish]
    bars: list[Bar] = Field(default_factory=list)

    def images(self) -> list[FoundImage]:
        """Every verified dish photo (regional dishes + eateries' must-try), once each."""
        found = [d.image for d in self.dishes if d.image]
        found += [m.image for e in self.eateries for m in e.must_try if m.image]
        return list({i.local_path: i for i in found}.values())

    def without_images(self) -> dict:
        return self.model_dump(exclude={"dishes": {"__all__": {"image"}},
                                        "eateries": {"__all__": {"must_try": {"__all__": {"image"}}}}})
