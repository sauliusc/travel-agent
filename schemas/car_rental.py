"""Car Rental agent output: 3 well-reviewed, good-value rental companies."""

from pydantic import BaseModel, Field

# Enforced in code (agents/car_rental.py), not just asked for in the prompt.
MIN_RATING = 4.0
MIN_REVIEWS = 30


class RentalCompany(BaseModel):
    name: str
    pickup_location: str = Field(description="where the car is picked up, e.g. 'Tirana Airport (TIA), terminal desk'")
    rating: float = Field(description="average review score normalised to a 0-5 scale")
    review_count: int
    review_source: str = Field(description="where the rating comes from, e.g. 'Google Maps', 'Trustpilot'")
    car_class: str = Field(description="suitable class for the group and luggage, e.g. 'SUV, 5 vietos'")
    price_estimate_eur: int = Field(description="total rental price for the trip dates, incl. basic insurance")
    why: str = Field(description="one or two sentences for travellers: why it's good value (in the trip's language)")
    booking_url: str


class CarTypeRecommendation(BaseModel):
    car_type: str = Field(description="class with typical models, e.g. 'Kompaktinis SUV (Dacia Duster, Skoda Karoq)'")
    why: str = Field(description="why it suits this group, luggage and roads, in the trip's language")
    avg_price_per_day_eur: int = Field(description="average market price per day for the trip dates")
    avg_total_eur: int = Field(description="average total for the whole rental period incl. basic insurance")


class CarRentalResults(BaseModel):
    needed: bool = Field(description="true only if the trip includes renting a car")
    recommended_car_types: list[CarTypeRecommendation] = Field(
        default_factory=list, description="2-3 suitable car classes, best fit first")
    companies: list[RentalCompany] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list, description="short practical rental tips in the trip's language")
