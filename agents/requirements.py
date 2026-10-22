"""Requirements Analyst agent: turns free-text trip requests into a structured
TripRequirements object.

Uses `claude -p --json-schema` for schema-validated output. This replaces
the Anthropic API's client.messages.parse() -- that's a Messages API
feature, not available once agents run through the Claude Code CLI on
subscription auth instead of an API key.
"""

import json
from pathlib import Path

from agents.base import ClaudeCLIError, _invoke_claude
from schemas.requirements import TripRequirements

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "requirements.md").read_text()


def analyze(free_text: str, timeout: int = 300) -> TripRequirements:
    """Extract structured trip requirements from a free-text request.

    Args:
        free_text: the user's trip request, usually in Lithuanian, e.g.
            "Albanija, 3 dienos, spalio 2-4, 2 zmones, automobilis, ..."
        timeout: seconds to wait for the subprocess before raising
    """
    schema = TripRequirements.model_json_schema()
    payload = _invoke_claude(
        SYSTEM_PROMPT,
        allowed_tools=[],
        user_input=free_text,
        timeout=timeout,
        extra_args=["--json-schema", json.dumps(schema)],
    )

    # The CLI's exact structured-output field name for --json-schema isn't
    # verified against a live call (that would spend real subscription
    # usage just to check a field name) -- the documented field is
    # "structured_output", but fall back to parsing "result" as JSON
    # directly in case the schema-validated payload comes back inline
    # instead. Whichever path is wrong will surface as a clear
    # ClaudeCLIError on the first real run, not a silent bad parse.
    structured = payload.get("structured_output")
    if structured is not None:
        return TripRequirements.model_validate(structured)

    text = payload.get("result")
    if text is None:
        raise ClaudeCLIError(
            f"claude JSON output missing both 'structured_output' and 'result': {payload!r}"
        )
    try:
        return TripRequirements.model_validate_json(text)
    except Exception as e:
        raise ClaudeCLIError(
            f"could not parse TripRequirements from claude's result text: {text[:500]!r}"
        ) from e
