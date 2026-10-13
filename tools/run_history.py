"""Human-readable agent execution history for one pipeline run.

Every run of a trip -- the initial request, a modification, a rerun from a
step, a retry -- becomes one Markdown file in the trip's repository under
request-history/: when it ran, its progress log, and every agent call with
the model used, the request sent and the answer, both formatted for reading
(JSON pretty-printed, generated HTML replaced by a one-line note).
"""

import datetime as dt
import json
import re

from tools.github import push_file

HISTORY_DIR = "request-history"
MAX_BLOCK = 40_000  # characters per request/answer block

_HTML_DOC = re.compile(r"<!DOCTYPE html>.*?</html>", re.S | re.I)


def _html_note(text: str) -> str:
    return _HTML_DOC.sub(lambda m: f"[HTML puslapis, {len(m.group(0)) // 1024} KB — nerodomas]", text)


def _pretty_json(text: str) -> str | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    if not isinstance(value, (dict, list)):
        return None
    return json.dumps(value, ensure_ascii=False, indent=2)


def _clip(text: str) -> str:
    if len(text) <= MAX_BLOCK:
        return text
    return text[:MAX_BLOCK] + f"\n… (sutrumpinta, iš viso {len(text)} simbolių)"


def _fence(text: str, lang: str = "") -> str:
    ticks = "````" if "```" in text else "```"
    return f"{ticks}{lang}\n{_clip(text)}\n{ticks}"


def readable(text: str) -> str:
    """Text with embedded JSON pretty-printed and HTML pages replaced by a note.
    Handles the request shapes agents get: paragraphs that are JSON, or
    `Label:\\n{json}` / `key={json}` paragraphs."""
    out = []
    for block in _html_note(text).strip().split("\n\n"):
        pretty = _pretty_json(block)
        if pretty is not None:
            out.append(_fence(pretty, "json"))
            continue
        head, sep, rest = block.partition("\n")
        if sep and (pretty := _pretty_json(rest)) is not None:
            out.append(f"**{head.strip()}**\n\n" + _fence(pretty, "json"))
            continue
        if all(_KEY_VALUE.match(line) for line in block.splitlines()):
            for line in block.splitlines():
                key, value = _KEY_VALUE.match(line).groups()
                pretty = _pretty_json(value)
                out.append(f"**{key}**\n\n" + (_fence(pretty, "json") if pretty is not None else _text(value)))
            continue
        out.append(_text(block))
    return "\n\n".join(out)


_KEY_VALUE = re.compile(r"^([A-Za-z_]+)=(.*)$")


def _text(block: str) -> str:
    """Plain prose shown as readable text (agents write Markdown anyway)."""
    return _clip(block.strip())


def readable_answer(stage: str, response: str) -> str:
    """The agent's answer: structured output as JSON, text as text, the page
    as a one-line note."""
    if response.startswith("ERROR"):
        return "❌ " + _fence(response)
    try:
        payload = json.loads(response)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        if payload.get("structured_output") is not None:
            return _fence(json.dumps(payload["structured_output"], ensure_ascii=False, indent=2), "json")
        text = payload.get("result") or ""
    else:
        text = response
    if stage == "page" or _HTML_DOC.search(text):
        size = len(text) // 1024
        return f"HTML puslapis sugeneruotas ({size} KB)." if "<html" in text.lower() else _fence(text)
    return readable(text) if text else "_(tuščias atsakymas)_"


STAGE_NAMES = {
    "requirements": "Reikalavimai", "research": "Tyrimas", "weather": "Oras/sezonas",
    "accommodation": "Nakvynė", "itinerary": "Dienų planas", "logistics_report": "Logistika",
    "images": "Nuotraukos", "car_rental": "Auto nuoma", "food": "Maistas ir barai",
    "plan_b": "Planas B", "packing": "Daiktai", "budget": "Biudžetas", "page": "Puslapis",
    "critic": "Peržiūra",
}


def render(run: dict) -> str:
    """Markdown for one run: {kind, started, finished, trip_id, profile, status,
    error, modification, events: [(time, message)], calls: [{time, stage, meta, response}]}."""
    lines = [
        f"# {run['kind']} — {run['started']:%Y-%m-%d %H:%M:%S %Z}",
        "",
        f"- **Kelionė:** `{run['trip_id']}`",
        f"- **Pradžia / pabaiga:** {run['started']:%Y-%m-%d %H:%M:%S} → {run['finished']:%H:%M:%S}"
        f" ({int((run['finished'] - run['started']).total_seconds() // 60)} min.)",
        f"- **Agentų rinkinys:** {run.get('profile') or 'Base'}",
        f"- **Rezultatas:** {'✅ Baigta' if run['status'] == 'done' else '❌ Nepavyko'}",
    ]
    if run.get("modification"):
        lines.append(f"- **Pataisymas:** {run['modification']}")
    if run.get("error"):
        lines.append(f"- **Klaida:** {run['error']}")
    lines += ["", "## Eiga", ""]
    lines += [f"- `{t:%H:%M:%S}` {msg}" for t, msg in run["events"]]
    lines += ["", f"## Agentų kvietimai ({len(run['calls'])})", ""]
    if not run["calls"]:
        lines.append("_Šiame paleidime agentai nekviesti (visi rezultatai paimti iš ankstesnių paleidimų)._")
    for i, call in enumerate(run["calls"], 1):
        meta = call.get("meta") or {}
        models = ", ".join(meta.get("models") or []) or "nežinomas"
        status = "✅" if meta.get("ok") else "❌"
        lines += [
            f"### {i}. {STAGE_NAMES.get(call['stage'], call['stage'])} — {call['time']:%H:%M:%S} {status}",
            "",
            f"- **Modelis:** `{models}` · **Vykdė:** {meta.get('provider', 'Native Claude (claude -p)')}"
            + (f" · **Trukmė:** {meta['duration_s']} s" if meta.get("duration_s") is not None else ""),
            f"- **Sistemos promptas:** `prompts/{meta['prompt_file']}`" if meta.get("prompt_file")
            else "- **Sistemos promptas:** (sudėtinis)",
            "",
            "<details><summary><b>Užklausa</b></summary>",
            "",
            readable(meta.get("user_input") or call.get("query") or ""),
            "",
            "</details>",
            "",
            "<details><summary><b>Atsakymas</b></summary>",
            "",
            readable_answer(call["stage"], call["response"]),
            "",
            "</details>",
            "",
        ]
    return "\n".join(lines) + "\n"


def file_name(run: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", run["kind_slug"].lower()).strip("-")
    return f"{HISTORY_DIR}/{run['started']:%Y-%m-%d_%H%M%S}_{slug}.md"


def publish(owner: str, repo: str, run: dict) -> str:
    """Push the run's history file into the trip repository; returns its path."""
    path = file_name(run)
    result = push_file(owner, repo, path, render(run), f"Request history: {run['kind']}")
    if result.startswith("Failed"):
        raise RuntimeError(result)
    return path


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()
