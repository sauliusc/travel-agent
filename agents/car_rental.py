"""Car Rental agent: 3 well-reviewed, good-value rental companies, when the
trip includes renting a car."""

from pathlib import Path

from agents.base import ClaudeCLIError, run_structured
from schemas.car_rental import MIN_RATING, MIN_REVIEWS, CarRentalResults

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "car_rental.md").read_text()
TIMEOUT = 900


def find(requirements_json: str, user_request: str) -> CarRentalResults:
    result = run_structured(
        SYSTEM_PROMPT, ["WebSearch", "WebFetch"],
        f"Trip requirements:\n{requirements_json}\n\nOriginal request:\n{user_request}",
        CarRentalResults, timeout=TIMEOUT,
    )
    if not result.needed:
        return CarRentalResults(needed=False)
    weak = [c.name for c in result.companies if c.rating < MIN_RATING or c.review_count < MIN_REVIEWS]
    if weak or len(result.companies) != 3:
        raise ClaudeCLIError(
            f"Car Rental agent must return 3 companies rated >= {MIN_RATING} from >= {MIN_REVIEWS} "
            f"reviews; got {len(result.companies)}, below the bar: {weak}"
        )
    return result
