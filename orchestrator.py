"""Main orchestration flow: requirements -> research/weather -> accommodation ->
itinerary -> logistics gate -> map/images -> car rental/food -> forecast/packing ->
budget -> page -> critic loop -> CI/CD deploy.

Stages declare their inputs (STAGE_DEPS); a rerun reuses every stage whose
inputs and prompt didn't change.

All 14 agents from the design doc are wired in.
"""

import hashlib
import json
import os
import re
from pathlib import Path

from agents.accommodation import find as run_accommodation
from agents.accommodation import update as update_accommodation
from agents.base import log_calls
from agents.budget import estimate as run_budget
from agents.car_rental import find as run_car_rental
from agents.cicd import deploy as run_cicd
from agents.cicd import page_url
from agents.critic import MAX_FIX_ITERATIONS, review
from schemas.review import issues_text
from tools.page_checks import check_page
from agents.food import guide as run_food
from agents.packing import plan as run_packing
from agents.plan_b import build as run_plan_b
from agents.images import fetch_images as run_images
from agents.itinerary import fix, plan
from agents.logistics import validate
from agents.page_designer import design as run_page_designer
from agents.page_designer import update as update_page
from agents.requirements import analyze as run_requirements_analyst
from agents.research import research as run_research
from agents.weather import check as run_weather
from schemas.car_rental import CarRentalResults
from schemas.food import FoodGuide
from schemas.forecast import TripForecast
from schemas.packing import PackingList
from schemas.plan_b import PlanBChecked
from schemas.images import ImageResults
from schemas.logistics import LogisticsReport
from schemas.requirements import TripRequirements
from schemas.itinerary import Itinerary
from tools.image_download import download_images
from tools.forecast import trip_forecast
from tools.maps_links import day_routes
from tools.packing_html import inject as inject_packing
from tools.packing_html import to_template as _packing_template
from tools.map_html import inject as inject_map, map_data
from tools.map_html import to_template as _map_template

REPO_PREFIX = "ai-trip-"

# How many times the planner may rework the itinerary on Logistics Validator
# blockers before the run stops. An unresolved road/timing problem must never
# reach the page as a "warning" -- travellers can't act on uncertainty.
MAX_LOGISTICS_FIXES = 2



def to_template(page_html: str) -> str | None:
    """Page with code-rendered blocks (packing list, map) back as placeholders."""
    t = _packing_template(page_html)
    return None if t is None else _map_template(t)

class LogisticsBlocked(RuntimeError):
    """The itinerary still has logistics blockers after MAX_LOGISTICS_FIXES reworks."""


def _blocker_text(report: LogisticsReport) -> str:
    return "\n".join(f"- {b.where}: {b.problem} -> {b.fix}" for b in report.blockers())


def _page_logistics(report: LogisticsReport) -> dict:
    # Traveller-facing facts only; `evidence` is internal.
    return {
        "legs": [leg.model_dump(exclude={"evidence", "confirmed"}) for leg in report.legs],
        "traveler_tips": report.traveler_tips,
    }

# Pipeline stages in dependency order. run_from_stage() uses this to decide,
# for a given starting stage, which earlier stages can be taken from
# cached_outputs (schemas/console.db's trip_stages) instead of recomputed.
STAGE_ORDER = [
    "requirements",
    "research",
    "weather",
    "accommodation",
    "itinerary",
    "logistics_report",
    "map_data",
    "images",
    "car_rental",
    "food",
    "forecast",
    "plan_b",
    "packing",
    "budget",
    "page",
    "deploy_log",
]


def _slugify(requirements) -> str:
    base = f"{requirements.destination}-{requirements.trip_type}"
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return f"{REPO_PREFIX}{slug}"


# What each stage reads. A stage is rerun only when the outputs of these
# stages (or its own prompt, or a stage-specific extra input) changed since
# it last ran -- otherwise its stored result is reused. E.g. car_rental
# depends only on the requirements, so an itinerary change doesn't redo it.
STAGE_DEPS: dict[str, list[str]] = {
    "requirements": [],
    "research": ["requirements"],
    "weather": ["requirements"],
    "accommodation": ["requirements", "research"],
    "itinerary": ["requirements", "research", "weather", "accommodation"],
    "logistics_report": ["itinerary"],
    "map_data": ["itinerary"],
    "images": ["itinerary"],
    "car_rental": ["requirements"],
    "food": ["requirements", "itinerary", "accommodation"],
    "forecast": ["requirements", "itinerary"],
    # Not the forecast: every weather-dependent day gets a Plan B regardless,
    # and a daily-changing forecast would otherwise redo it on every run.
    "plan_b": ["requirements", "itinerary"],
    "packing": ["requirements", "itinerary", "forecast", "car_rental"],
    "budget": ["itinerary", "accommodation", "car_rental", "food"],
    "page": ["requirements", "itinerary", "logistics_report", "budget", "map_data", "images",
             "car_rental", "food", "forecast", "plan_b", "packing"],
    "deploy_log": ["page", "images", "food"],
}

# Prompt files per stage: editing a prompt invalidates that stage's results.
_PROMPTS = Path(__file__).parent / "prompts"
STAGE_PROMPTS: dict[str, list[str]] = {
    "requirements": ["requirements.md"], "research": ["research.md"], "weather": ["weather.md"],
    "accommodation": ["accommodation.md"], "itinerary": ["itinerary.md"],
    "logistics_report": ["logistics.md"], "images": ["images.md"],
    "car_rental": ["car_rental.md"], "food": ["food.md"], "plan_b": ["plan_b.md"], "packing": ["packing.md"],
    "budget": ["budget.md"], "page": ["page_designer.md", "critic.md"],
}

STAGE_LABELS = {
    "requirements": "Reikalavimai", "research": "Tyrimas", "weather": "Oras/sezonas",
    "accommodation": "Nakvynė", "itinerary": "Dienų planas", "logistics_report": "Logistika",
    "map_data": "Žemėlapis", "images": "Nuotraukos", "car_rental": "Auto nuoma",
    "food": "Maistas ir barai", "forecast": "Orų prognozė", "plan_b": "Planas B",
    "packing": "Daiktai",
    "budget": "Biudžetas", "page": "Puslapis", "deploy_log": "Publikavimas",
}

FP_PREFIX = "_fp:"


def _only_stops(itinerary: Itinerary, names: set[str]) -> Itinerary:
    """The itinerary reduced to the given stops (days without any dropped)."""
    days = []
    for day in itinerary.days:
        stops = [s for s in day.stops if s.name in names]
        if stops:
            days.append(day.model_copy(update={"stops": stops}))
    return Itinerary(days=days)


def run_from_stage(
    stage_name: str,
    cached_outputs: dict[str, str] | None = None,
    on_progress=None,
    on_stage_complete=None,
    on_llm_call=None,
    modification: str | None = None,
    user_requirements: str | None = None,
) -> str:
    """Run the pipeline from `stage_name` to CI/CD deploy and return the
    published page's URL.

    Stages before `stage_name` are taken from cached_outputs. `stage_name`
    itself always runs. Every later stage runs only if its inputs changed
    (see STAGE_DEPS); otherwise its stored result is reused. The stored
    fingerprints live next to the outputs as "_fp:<stage>" entries, so they
    persist through on_stage_complete like any other stage output.

    Within a stage that does run, work is reused where it's safe: images are
    looked up only for stops that have no photo decision yet, and the
    Logistics Validator gets the previous report so unchanged legs needn't be
    re-checked.

    Args:
        stage_name: one of STAGE_ORDER -- the stage to (re)run from
        cached_outputs: persisted stage outputs (+ "_fp:" fingerprints)
        on_progress / on_stage_complete / on_llm_call: see run_travel_planner
        modification: free-text change to an existing trip. Applied to
            accommodation (if it concerns lodging) and the itinerary, both of
            which are then rerun; use stage_name="accommodation".
        user_requirements: the original free-text trip request
    """
    if stage_name not in STAGE_ORDER:
        raise ValueError(f"Unknown stage {stage_name!r}, must be one of {STAGE_ORDER}")

    out: dict[str, str] = dict(cached_outputs or {})
    progress = on_progress or (lambda _msg: None)
    stage_done = on_stage_complete or (lambda _stage, _output: None)
    start_idx = STAGE_ORDER.index(stage_name)
    forced = {stage_name}
    if modification is not None:
        forced |= {"accommodation", "itinerary"} & set(STAGE_ORDER[start_idx:])
    extra = {
        "requirements": user_requirements or "",
        "car_rental": user_requirements or "",
        "packing": user_requirements or "",
    }

    def fingerprint(stage: str) -> str:
        h = hashlib.sha256(stage.encode())
        for name in STAGE_PROMPTS.get(stage, []):
            h.update(b"\0" + (_PROMPTS / name).read_bytes())
        for dep in STAGE_DEPS[stage]:
            h.update(b"\0" + out[dep].encode())
        h.update(b"\0" + extra.get(stage, "").encode())
        return h.hexdigest()

    def must_run(stage: str) -> bool:
        if STAGE_ORDER.index(stage) < start_idx:
            if stage not in out:
                raise ValueError(f"No stored result for stage {stage!r} -- run from an earlier stage")
            return False
        if stage in forced or stage not in out:
            return True
        if out.get(FP_PREFIX + stage) == fingerprint(stage):
            progress(f"{STAGE_LABELS[stage]}: įvestis nepasikeitė -- naudojamas ankstesnis rezultatas.")
            return False
        return True

    # What changed in this run, for the Page Designer's update mode.
    changes: list[str] = []
    changed_stages: list[str] = []

    def save(stage: str, value: str) -> None:
        if out.get(stage) != value and stage not in changed_stages:
            changed_stages.append(stage)
        out[stage] = value
        stage_done(stage, value)
        fp = fingerprint(stage)
        out[FP_PREFIX + stage] = fp
        stage_done(FP_PREFIX + stage, fp)

    # --- requirements, research, weather -----------------------------------
    if must_run("requirements"):
        if user_requirements is None:
            raise ValueError("user_requirements is required to (re)run the requirements stage")
        progress("Reikalavimų analizė...")
        with log_calls("requirements", on_llm_call):
            save("requirements", run_requirements_analyst(user_requirements).model_dump_json())
    requirements_json = out["requirements"]
    requirements = TripRequirements.model_validate_json(requirements_json)

    if must_run("research"):
        progress("Tyrimas (kelionės objektai, keliai, sezoniškumas)...")
        with log_calls("research", on_llm_call):
            save("research", run_research(requirements_json))

    if must_run("weather"):
        progress("Orų/sezono patikra...")
        with log_calls("weather", on_llm_call):
            save("weather", run_weather(requirements_json))

    # --- accommodation -----------------------------------------------------
    if must_run("accommodation"):
        if modification is not None and "accommodation" in out:
            progress("Nakvynė: taikomas pataisymas...")
            with log_calls("accommodation", on_llm_call):
                update = update_accommodation(out["accommodation"], modification, requirements_json)
            if not update.changed:
                progress("Nakvynė: pataisymas nakvynės neliečia -- paliekama kaip buvo.")
            save("accommodation", update.accommodation if update.changed else out["accommodation"])
        else:
            progress("Nakvynės paieška...")
            with log_calls("accommodation", on_llm_call):
                save("accommodation", run_accommodation(f"requirements={requirements_json}\nresearch={out['research']}"))
    accommodation = out["accommodation"]

    # --- itinerary + logistics gate ----------------------------------------
    if must_run("itinerary"):
        if modification is not None and "itinerary" in out:
            progress("Dienų plano koregavimas pagal nurodymą...")
            with log_calls("itinerary", on_llm_call):
                new_itinerary, summary = fix(out["itinerary"], f"{modification}\n\nCurrent accommodation:\n{accommodation}")
            save("itinerary", new_itinerary)
            changes += [f"Traveller's change request: {modification}", f"Itinerary: {summary}"]
        else:
            progress("Dienų plano sudarymas...")
            with log_calls("itinerary", on_llm_call):
                save("itinerary", plan(
                    f"requirements={requirements_json}\nresearch={out['research']}\n"
                    f"weather={out['weather']}\naccommodation={accommodation}"
                ))

    def validate_until_ok(itinerary: str, previous: LogisticsReport | None) -> LogisticsReport:
        """Validate; on blockers let the planner rework the itinerary and
        re-validate, so only a fully confirmed itinerary moves on."""
        for attempt in range(MAX_LOGISTICS_FIXES + 1):
            progress("Logistikos patikra (važiavimo laikai, keliai)..." if attempt == 0
                     else f"Pakartotinė logistikos patikra ({attempt}/{MAX_LOGISTICS_FIXES})...")
            with log_calls("logistics_report", on_llm_call):
                report = validate(itinerary, previous)
            save("logistics_report", report.model_dump_json())
            if report.ok():
                return report
            if attempt == MAX_LOGISTICS_FIXES:
                break
            progress(f"Logistika rado {len(report.blockers())} problemą(-as) -- dienų planas perdaromas...")
            with log_calls("itinerary", on_llm_call):
                itinerary, summary = fix(itinerary, "Logistics Validator blockers:\n" + _blocker_text(report))
            save("itinerary", itinerary)
            changes.append(f"Itinerary (logistics fix): {summary}")
            previous = report
        raise LogisticsBlocked(
            f"Logistika nepatvirtino maršruto po {MAX_LOGISTICS_FIXES} perdarymų:\n"
            f"{_blocker_text(report)}\nPakoreguok kelionę per „Pataisyti“ ir paleisk iš naujo."
        )

    def previous_report() -> LogisticsReport | None:
        if "logistics_report" not in out or "logistics_report" in forced:
            return None
        try:
            return LogisticsReport.model_validate_json(out["logistics_report"])
        except ValueError:  # free-text report from before the structured schema
            return None

    if must_run("logistics_report"):
        logistics_report = validate_until_ok(out["itinerary"], previous_report())
    else:
        logistics_report = LogisticsReport.model_validate_json(out["logistics_report"])
        if not logistics_report.ok():
            raise LogisticsBlocked(
                "Išsaugota logistikos ataskaita turi neišspręstų problemų -- paleisk nuo „Logistika“:\n"
                + _blocker_text(logistics_report)
            )

    # --- map, images -------------------------------------------------------
    if must_run("map_data"):
        # Built from the itinerary by code -- no agent call.
        progress("Žemėlapio duomenų ruošimas...")
        save("map_data", json.dumps(map_data(Itinerary.model_validate_json(out["itinerary"])), ensure_ascii=False))

    if must_run("images"):
        itin = Itinerary.model_validate_json(out["itinerary"])
        stop_names = {s.name for d in itin.days for s in d.stops}
        prev = None
        if "images" in out and "images" not in forced:
            prev = ImageResults.model_validate_json(out["images"])
        if prev is None:
            todo, kept, skipped = stop_names, [], {}
        else:
            decided = {img.stop_name for img in prev.images} | set(prev.skipped)
            todo = stop_names - decided
            kept = [img for img in prev.images if img.stop_name in stop_names]
            skipped = {k: v for k, v in prev.skipped.items() if k in stop_names}
        if todo:
            progress(f"Nuotraukų paieška ({len(todo)} vietoms)...")
            with log_calls("images", on_llm_call):
                picks = run_images(_only_stops(itin, todo).model_dump_json())
            progress("Nuotraukų atsisiuntimas ir licencijų patikra...")
            fresh = download_images(picks)
            kept += fresh.images
            skipped |= fresh.skipped
            if fresh.skipped:
                progress(f"Praleista nuotraukų: {len(fresh.skipped)} ({'; '.join(f'{k}: {v}' for k, v in fresh.skipped.items())})")
        else:
            progress("Nuotraukos: visoms vietoms jau yra -- nauja paieška nereikalinga.")
        save("images", ImageResults(images=kept, skipped=skipped).model_dump_json())
    images = ImageResults.model_validate_json(out["images"])

    # --- car rental, food, forecast, packing -------------------------------
    if must_run("car_rental"):
        progress("Automobilio nuomos pasiūlymai...")
        with log_calls("car_rental", on_llm_call):
            result = run_car_rental(requirements_json, user_requirements or "")
        if not result.needed:
            progress("Automobilio nuoma šiai kelionei nereikalinga -- praleidžiama.")
        save("car_rental", result.model_dump_json())
    car_rental = CarRentalResults.model_validate_json(out["car_rental"])

    if must_run("food"):
        progress("Maistas, vietiniai patiekalai ir barai...")
        with log_calls("food", on_llm_call):
            save("food", run_food(requirements_json, out["itinerary"], accommodation).model_dump_json())
    food = FoodGuide.model_validate_json(out["food"])

    # Code only and cheap, and its input includes "today" (forecast vs climate),
    # so it always runs; packing still reruns only if the result changed.
    if STAGE_ORDER.index("forecast") >= start_idx:
        progress("Orų prognozė...")
        save("forecast", trip_forecast(Itinerary.model_validate_json(out["itinerary"]),
                                       requirements.start_date).model_dump_json())
    forecast = TripForecast.model_validate_json(out["forecast"])

    if must_run("plan_b"):
        progress("Planas B blogam orui (alternatyvos ir kelių patikra)...")
        with log_calls("plan_b", on_llm_call):
            save("plan_b", run_plan_b(requirements_json, out["itinerary"], out["forecast"]).model_dump_json())
    plan_b = PlanBChecked.model_validate_json(out["plan_b"])

    if must_run("packing"):
        progress("Daiktų sąrašas...")
        with log_calls("packing", on_llm_call):
            save("packing", run_packing(requirements_json, user_requirements or "", out["itinerary"],
                                        out["forecast"], car_rental.needed).model_dump_json())
    packing = PackingList.model_validate_json(out["packing"])

    # Stop photos and dish photos are shipped together.
    all_images = ImageResults(
        images=[*images.images, *(d.image for d in food.dishes if d.image)],
        skipped=images.skipped,
    )

    if must_run("budget"):
        progress("Biudžeto skaičiavimas...")
        with log_calls("budget", on_llm_call):
            save("budget", run_budget({
                "itinerary": out["itinerary"], "accommodation": accommodation,
                "car_rental": car_rental.model_dump(), "food": food.model_dump(exclude={"dishes": {"__all__": {"image"}}}),
            }))

    # --- page, critic, deploy ----------------------------------------------
    def page_context() -> dict:
        return {
            "language": requirements.language,
            "itinerary": out["itinerary"],
            "day_routes": day_routes(Itinerary.model_validate_json(out["itinerary"])),
            "logistics": _page_logistics(logistics_report),
            "budget": out["budget"],
            "map_data": "rendered by code -- only place the <!-- TRIP_MAP --> placeholder",
            "images": images.model_dump(),
            "car_rental": car_rental.model_dump(),
            "food": food.model_dump(),
            "forecast": forecast.model_dump(),
            "plan_b": plan_b.model_dump(),
            "packing": "rendered by code -- only place the <!-- PACKING_LIST --> placeholder",
        }

    repo_name = _slugify(requirements)

    def design_page(update_notes: list[str] | None) -> str:
        """Generate the page, or -- with update_notes and an existing page --
        update that page in place so its design and untouched text stay put.
        The checklist (checkboxes + localStorage) is rendered by code either way."""
        template = to_template(out["page"]) if update_notes is not None and "page" in out else None
        if template is None:
            html = run_page_designer(page_context())
        else:
            labels = ", ".join(STAGE_LABELS.get(st, st) for st in changed_stages if st in STAGE_LABELS) or "-"
            if "<!-- TRIP_MAP -->" not in template:
                update_notes = [*update_notes, "Replace the whole map (its container, Leaflet <link>/<script> "
                                "and map JS) with the single line <!-- TRIP_MAP --> -- the map is now rendered by code."]
            html = update_page(template, page_context(), "\n".join([*update_notes, f"Updated data: {labels}"]))
        html = inject_map(html, map_data(Itinerary.model_validate_json(out["itinerary"])))
        return inject_packing(html, packing, f"packing:{repo_name}")

    if must_run("page"):
        # A manual "↻ Puslapis" redesigns from scratch; any other rerun updates
        # the existing page so the trip page doesn't change look on every tweak.
        full = "page" in forced or to_template(out.get("page", "")) is None
        progress("Puslapio generavimas..." if full else "Puslapio atnaujinimas (dizainas išlaikomas)...")
        with log_calls("page", on_llm_call):
            save("page", design_page(None if full else changes))
        # Code checks first (free), then the critic. Page-only findings update
        # the page alone; only itinerary blockers rework the plan + logistics.
        # Minor findings never start a round -- they ride along with the next update.
        fixed: list[str] = []
        for attempt in range(MAX_FIX_ITERATIONS):
            code_problems = check_page(out["page"], {i.local_path for i in all_images.images},
                                       page_context()["day_routes"], logistics_report.traveler_tips)
            if code_problems:
                progress(f"Puslapio patikra rado {len(code_problems)} netikslumų - taisomas tik puslapis...")
                notes = "\n".join(f"- {p}" for p in code_problems)
            else:
                progress(f"Peržiūra (bandymas {attempt + 1}/{MAX_FIX_ITERATIONS})...")
                with log_calls("critic", on_llm_call):
                    result = review(out["page"], out["itinerary"], logistics_report.model_dump_json(),
                                    all_images.model_dump_json(),
                                    json.dumps(page_context()["day_routes"], ensure_ascii=False),
                                    "\n".join(fixed))
                if not result.blockers():
                    if result.issues:
                        progress(f"Peržiūra: {len(result.issues)} smulkių pastabų, puslapis tinkamas.")
                    break
                notes = issues_text(result.issues)
                fixed.append(notes)
                itinerary_issues = [i for i in result.blockers() if i.target == "itinerary"]
                if itinerary_issues:
                    progress("Taisomas dienų planas pagal peržiūrą...")
                    with log_calls("itinerary", on_llm_call):
                        new_itinerary, summary = fix(out["itinerary"], issues_text(itinerary_issues))
                    save("itinerary", new_itinerary)
                    logistics_report = validate_until_ok(out["itinerary"], logistics_report)
                    notes += f"\nItinerary: {summary}"
                else:
                    progress("Taisomas tik puslapis pagal peržiūrą...")
            with log_calls("page", on_llm_call):
                save("page", design_page([f"Fix these review findings:\n{notes}"]))

    owner = os.environ.get("GITHUB_OWNER", "sauliusc")
    if must_run("deploy_log"):
        progress("Repozitorijos kūrimas ir puslapio publikavimas...")
        deploy_log = run_cicd(
            owner=owner,
            repo_name=repo_name,
            description=f"{requirements.destination} trip page",
            page_html=out["page"],
            images=all_images,
        )
        save("deploy_log", deploy_log)
        print(deploy_log)
    return page_url(owner, repo_name)


def run_travel_planner(user_requirements: str, on_progress=None, on_stage_complete=None, on_llm_call=None) -> str:
    """Run the full pipeline for one trip request and return the published page's URL.

    Args:
        user_requirements: free-text trip request from the user
        on_progress: optional callable(str) invoked with a short status line
            before each agent stage -- each `claude -p` call inside a stage
            can itself take a while (real reasoning, real subscription
            usage), so without this the caller sees nothing at all between
            "started" and "finished", which looks identical to hung.
        on_stage_complete: optional callable(stage_name: str, output: str)
            invoked right after each stage produces its (string) output, so
            a caller can persist it for later inspection/rerun without
            re-running the whole pipeline.
        on_llm_call: optional callable(stage_name: str, query: str,
            response: str) invoked after every real `claude -p` call
            (system prompt + input as `query`, raw CLI JSON as `response`)
            -- lets a caller persist the actual agent conversation for
            inspection, without needing to grep `ps aux`/journalctl on the
            machine the pipeline runs on.
    """
    return run_from_stage(
        "requirements",
        on_progress=on_progress,
        on_stage_complete=on_stage_complete,
        on_llm_call=on_llm_call,
        user_requirements=user_requirements,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python orchestrator.py '<free-text trip requirements>'")
        sys.exit(1)
    run_travel_planner(sys.argv[1])
