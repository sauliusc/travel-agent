"""Image agent: finds a Wikimedia Commons photo for every stop in the itinerary.

Uses `claude -p --json-schema` (same pattern as agents/requirements.py) so
the result is a structured ImageResults list agents/cicd.py can render
directly into fetch-images.yml's file list, instead of the free-text
summary the CI/CD agent previously had to embed as an unfilled comment.
"""

import json
from pathlib import Path

from agents.base import ClaudeCLIError, _invoke_claude
from schemas.images import ImageResults

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "images.md").read_text()

TOOL_HINT = (
    'Use Bash to look up each stop: `python3 tools/wikimedia.py --query "<place name>"`.'
)


def fetch_images(itinerary_json: str, timeout: int = 300) -> ImageResults:
    """Find a licensed Wikimedia Commons image for every stop in the itinerary.

    Args:
        itinerary_json: JSON-serialized Itinerary (see schemas/itinerary.py)
        timeout: seconds to wait for the subprocess before raising
    """
    task = f"{itinerary_json}\n\n{TOOL_HINT}"
    schema = ImageResults.model_json_schema()
    payload = _invoke_claude(
        SYSTEM_PROMPT,
        allowed_tools=["Bash"],
        user_input=task,
        timeout=timeout,
        extra_args=["--json-schema", json.dumps(schema)],
    )

    # Same dual-path parsing as requirements.py, for the same reason: the
    # exact --json-schema output field isn't independently verifiable
    # without spending real subscription usage, so try the documented
    # "structured_output" field first, then fall back to "result" as JSON.
    structured = payload.get("structured_output")
    if structured is not None:
        return ImageResults.model_validate(structured)

    text = payload.get("result")
    if text is None:
        raise ClaudeCLIError(
            f"claude JSON output missing both 'structured_output' and 'result': {payload!r}"
        )
    try:
        return ImageResults.model_validate_json(text)
    except Exception as e:
        raise ClaudeCLIError(
            f"could not parse ImageResults from claude's result text: {text[:500]!r}"
        ) from e
