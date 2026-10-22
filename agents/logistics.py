"""Logistics Validator agent: checks every itinerary leg against real road data,
researching deeper when the tools can't confirm a road.

Each leg's travel mode (car / walk / transit) comes from the itinerary and is
enforced in code afterwards (enforce_modes): a walk always gets a walking
time, never the car time the agent may have copied from route_check, and a
trip without a car never gets a car leg.
"""

import json
import math
from pathlib import Path

from agents.base import ClaudeCLIError, _invoke_claude
from schemas.itinerary import Itinerary
from schemas.logistics import LegCheck, LogisticsIssue, LogisticsReport
from tools.route_check import walk_check

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "logistics.md").read_text()

# route_check per leg plus web research on any leg it can't confirm.
TIMEOUT = 1200

TOOL_HINT = (
    "Check each leg with ONE call: `python3 tools/route_check.py --from-lat .. --from-lon .. "
    "--to-lat .. --to-lon ..` -- it returns real distance/time and the road type at points "
    "sampled along the actual route, ending in `LEG OK`, `LEG WARNING` (not paved/drivable) or "
    "`LEG UNKNOWN` (road data service unreachable -- not a road problem; retry that leg once, then "
    "research it as unconfirmed). Run legs one "
    "after another, not in parallel (Overpass rate-limits parallel requests). Do not call "
    "OSRM/Overpass with curl yourself. `python3 tools/overpass.py --lat .. --lon ..` is only for "
    "spot-checking one specific point.\n"
    "Each stop's `arrive_by` says how the travellers get there from the previous stop: check "
    "'car' legs as above; for 'walk' legs run `python3 tools/route_check.py --mode walk ...` "
    "(walking time, no road check); for 'transit' legs confirm with web search that the line in "
    "the stop's `transit` runs on the trip dates, and give the door-to-door time and ticket."
)

# Longer walks go by public transport instead.
MAX_WALK_KM = 5.0
SAME_PLACE_KM = 0.3


def _km(a, b) -> float:
    kx = 111.32 * math.cos(math.radians((a.lat + b.lat) / 2))
    return math.hypot((a.lon - b.lon) * kx, (a.lat - b.lat) * 110.54)


def _key(day: int, a: str, b: str) -> tuple:
    return day, " ".join(a.split()).casefold(), " ".join(b.split()).casefold()


def enforce_modes(report: LogisticsReport, itinerary: Itinerary, transport: str,
                  max_driving_hours: float | None = None, walk=walk_check) -> LogisticsReport:
    """Rebuild the report's legs in itinerary order with the itinerary's travel
    modes: walking legs get a computed walking time, a car leg on a trip
    without a car or a walk over MAX_WALK_KM is a blocker, a transit leg needs
    a named line, and car driving per day stays within the limit."""
    by_key = {_key(l.day, l.from_stop, l.to_stop): l for l in report.legs}
    # Fallback when the agent spelled the start differently: same day, same destination.
    by_dest = {(k[0], k[2]): l for k, l in by_key.items()}
    legs, issues = [], [i for i in report.issues]
    for day in itinerary.days:
        drive = 0
        for a, b in zip(day.stops, day.stops[1:]):
            where = f"Day {day.number}: {a.name} -> {b.name}"
            k = _key(day.number, a.name, b.name)
            leg = by_key.get(k) or by_dest.get((k[0], k[2]))
            mode = b.arrive_by
            if mode == "car" and transport != "car":
                issues.append(LogisticsIssue(
                    severity="blocker", where=where, problem="the travellers have no car on this trip",
                    fix=f"walk (up to {MAX_WALK_KM:.0f} km) or take public transport, naming the best line"))
            if mode == "walk":
                w = walk(a.lat, a.lon, b.lat, b.lon)
                road = leg.road if leg is not None and leg.mode == "walk" else ""
                leg = LegCheck(day=day.number, from_stop=a.name, to_stop=b.name, mode="walk",
                               distance_km=round(w["km"], 1), minutes=max(1, round(w["minutes"])),
                               road=road, confirmed=True, evidence=w["text"])
                if w["km"] > MAX_WALK_KM:
                    issues.append(LogisticsIssue(
                        severity="blocker", where=where, problem=f"{w['km']:.1f} km is too far to walk",
                        fix="take public transport (name the best option: metro, tram, bus...) and walk "
                            "only between nearby stops"))
            elif leg is None:
                if _km(a, b) < SAME_PLACE_KM:  # next door -- the agent rightly skips it
                    leg = LegCheck(day=day.number, from_stop=a.name, to_stop=b.name, mode=mode,
                                   distance_km=0, minutes=0, road="", confirmed=True, evidence="same place")
                else:
                    issues.append(LogisticsIssue(severity="blocker", where=where, problem="leg was not checked",
                                                 fix="check this leg"))
                    continue
            else:
                # Checked in another mode (e.g. a car time for a metro ride): its time
                # is wrong, so it is unconfirmed -- re-checked, never reused.
                wrong_mode = leg.mode != mode
                leg = leg.model_copy(update={"mode": mode, "from_stop": a.name, "to_stop": b.name,
                                             "confirmed": leg.confirmed and not wrong_mode})
                if mode == "transit":
                    leg.road = ""
                    leg.transit = leg.transit or b.transit
                    if not leg.transit:
                        issues.append(LogisticsIssue(
                            severity="blocker", where=where, problem="no public transport option named",
                            fix="name the best option: line, where to board and get off"))
                else:
                    leg.transit_kind, leg.transit = "", ""
            if leg.mode == "car":
                drive += leg.minutes
            legs.append(leg)
        if max_driving_hours and drive > max_driving_hours * 60:
            issues.append(LogisticsIssue(
                severity="blocker", where=f"Day {day.number}",
                problem=f"{drive / 60:.1f} h of driving exceeds the {max_driving_hours} h daily limit",
                fix="drop or move a stop, or split the day"))
    passed = report.passed and not any(i.severity == "blocker" for i in issues)
    return report.model_copy(update={"legs": legs, "issues": issues, "passed": passed})


REUSE_HINT = (
    "Previous validation report for an earlier version of this itinerary is below. For a leg "
    "with the same from/to stops as a leg confirmed there, reuse that result (distance, time, "
    "road, evidence) without running route_check again; check only new or changed legs. "
    "Daily totals and the airport buffer must still be recomputed for the current plan."
)


def validate(itinerary_json: str, previous: LogisticsReport | None = None,
             transport: str = "car", max_driving_hours: float | None = None) -> LogisticsReport:
    """Validate an itinerary's legs; returns a structured report whose ok()
    decides whether the itinerary may proceed to the page. With `previous`,
    already-confirmed unchanged legs are reused, not re-checked."""
    no_car = ("\n\nThis trip has NO car: there must be no 'car' legs (report any as a blocker) and no "
              "driving tips -- traveller_tips are about public transport and walking." if transport != "car" else "")
    task = f"{itinerary_json}\n\n{TOOL_HINT}{no_car}"
    if previous is not None:
        task += f"\n\n{REUSE_HINT}\n{previous.model_dump_json()}"
    payload = _invoke_claude(
        SYSTEM_PROMPT,
        allowed_tools=["Bash", "WebSearch", "WebFetch"],
        user_input=task,
        timeout=TIMEOUT,
        extra_args=["--json-schema", json.dumps(LogisticsReport.model_json_schema())],
    )
    structured = payload.get("structured_output")
    if structured is not None:
        report = LogisticsReport.model_validate(structured)
    else:
        text = payload.get("result")
        if text is None:
            raise ClaudeCLIError(f"claude JSON output missing both 'structured_output' and 'result': {payload!r}")
        try:
            report = LogisticsReport.model_validate_json(text)
        except Exception as e:
            raise ClaudeCLIError(f"Logistics Validator did not return a valid report: {text[:500]!r}") from e
    return enforce_modes(report, Itinerary.model_validate_json(itinerary_json), transport, max_driving_hours)
