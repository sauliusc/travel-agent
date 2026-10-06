"""Plan B agent: a bad-weather alternative for every weather-dependent day,
which must start and end where the main plan does and pass the same road
checks. The constraints are verified in code; violations go back to the
agent once."""

import math
from pathlib import Path

from agents.base import ClaudeCLIError, run_structured
from schemas.itinerary import Itinerary
from schemas.plan_b import PlanB, PlanBChecked
from schemas.requirements import TripRequirements
from tools.maps_links import day_routes
from tools.route_check import leg_check

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "plan_b.md").read_text()
TIMEOUT = 1200
SAME_PLACE_KM = 2.0


def _km(a, b) -> float:
    kx = 111.32 * math.cos(math.radians((a.lat + b.lat) / 2))
    return math.hypot((a.lon - b.lon) * kx, (a.lat - b.lat) * 110.54)


def check(plan_b: PlanB, itinerary: Itinerary, max_driving_hours: float, route=None) -> tuple[list[str], dict[int, int]]:
    """Problems found in a Plan B, and each needed day's driving minutes."""
    route = route or leg_check
    main = {d.number: d for d in itinerary.days}
    problems, minutes = [], {}
    for alt in plan_b.days:
        if not alt.needed:
            continue
        day = main.get(alt.day)
        if day is None or not day.stops:
            problems.append(f"Day {alt.day}: no such day in the itinerary")
            continue
        if len(alt.stops) < 2:
            problems.append(f"Day {alt.day}: the alternative needs at least a start and an end stop")
            continue
        if _km(alt.stops[0], day.stops[0]) > SAME_PLACE_KM:
            problems.append(f"Day {alt.day}: must start at '{day.stops[0].name}' ({day.stops[0].lat}, {day.stops[0].lon}) like the main plan")
        if _km(alt.stops[-1], day.stops[-1]) > SAME_PLACE_KM:
            problems.append(f"Day {alt.day}: must end at '{day.stops[-1].name}' ({day.stops[-1].lat}, {day.stops[-1].lon}) like the main plan, so the next day still works")
        total = 0.0
        for a, b in zip(alt.stops, alt.stops[1:]):
            if _km(a, b) < 0.3:
                continue
            try:
                leg = route(a.lat, a.lon, b.lat, b.lon)
            except Exception as e:  # noqa: BLE001 - an unreachable router is a failed check, not a crash
                problems.append(f"Day {alt.day}: {a.name} -> {b.name} could not be checked ({e})")
                continue
            total += leg["minutes"]
            if not leg["ok"]:
                problems.append(f"Day {alt.day}: {a.name} -> {b.name} is not confirmed paved/drivable:\n{leg['text']}")
        minutes[alt.day] = round(total)
        if total > max_driving_hours * 60:
            problems.append(f"Day {alt.day}: {total / 60:.1f} h of driving exceeds the {max_driving_hours} h daily limit")
    return problems, minutes


def build(requirements_json: str, itinerary_json: str, forecast_json: str) -> PlanBChecked:
    requirements = TripRequirements.model_validate_json(requirements_json)
    itinerary = Itinerary.model_validate_json(itinerary_json)
    task = (f"Trip requirements:\n{requirements_json}\n\nItinerary (main plan):\n{itinerary_json}\n\n"
            f"Weather for the trip dates:\n{forecast_json}")
    tools = ["WebSearch", "WebFetch", "Bash"]
    plan_b = run_structured(SYSTEM_PROMPT, tools, task, PlanB, timeout=TIMEOUT)
    problems, minutes = check(plan_b, itinerary, requirements.max_driving_hours_per_day)
    if problems:
        retry = (f"{task}\n\nYour previous Plan B:\n{plan_b.model_dump_json()}\n\n"
                 "It has these problems -- fix them and return the complete Plan B:\n- " + "\n- ".join(problems))
        plan_b = run_structured(SYSTEM_PROMPT, tools, retry, PlanB, timeout=TIMEOUT)
        problems, minutes = check(plan_b, itinerary, requirements.max_driving_hours_per_day)
    if problems:
        raise ClaudeCLIError("Planas B neatitinka reikalavimų po pataisymo:\n- " + "\n- ".join(problems))

    needed = [d for d in plan_b.days if d.needed]
    routes = {r["day"]: r["urls"] for r in day_routes(Itinerary.model_validate(
        {"days": [{"number": d.day, "title": d.title, "stops": [s.model_dump() for s in d.stops],
                   "driving_minutes": minutes[d.day], "overnight_city": ""} for d in needed]}))}
    return PlanBChecked(days=plan_b.days, driving_minutes=minutes, route_urls=routes)
