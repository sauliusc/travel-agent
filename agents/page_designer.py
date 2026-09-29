"""Page Designer agent: generates the final single-file index.html trip page."""

import json
import re
from pathlib import Path

from agents.base import ClaudeCLIError, _invoke_claude

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "page_designer.md").read_text()

# Full-page HTML generation can run long -- give the subprocess more time
# than the 600s default used by shorter agent turns.
TIMEOUT = 900

OUTPUT_RULE = (
    "Reply with the complete HTML document itself as your entire answer, starting with "
    "<!DOCTYPE html>. Do not write files, and do not describe or summarise what you did."
)


def extract_html(text: str) -> str:
    """The HTML document from the agent's answer, or ClaudeCLIError if there isn't one.

    Tolerates a ```html fence around it; rejects anything that isn't a full
    document (a real run returned a prose summary, which got published).
    """
    fenced = re.search(r"```(?:html)?\s*\n(.*?)```", text, re.S | re.I)
    html = (fenced.group(1) if fenced else text).strip()
    start = re.search(r"<!doctype html|<html", html, re.I)
    if not start or not re.search(r"</html>\s*$", html, re.I):
        raise ClaudeCLIError(
            f"Page Designer did not return a complete HTML document: {text[:300]!r}"
        )
    return html[start.start():]


def design(context: dict) -> str:
    """Generate the complete index.html for a trip.

    Args:
        context: page inputs (language, itinerary, logistics, budget, map_data, images)
    """
    payload = _invoke_claude(
        SYSTEM_PROMPT,
        allowed_tools=[],
        user_input=f"{json.dumps(context, ensure_ascii=False)}\n\n{OUTPUT_RULE}",
        timeout=TIMEOUT,
        # Pure generation from the given inputs: no reading the repo's stale
        # drafts, no shell.
        disallowed_tools=["Bash", "Read", "Glob", "Grep", "WebSearch", "WebFetch"],
    )
    text = payload.get("result")
    if text is None:
        raise ClaudeCLIError(f"claude JSON output missing 'result' field: {payload!r}")
    return extract_html(text)
