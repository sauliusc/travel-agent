"""Requirements Analyst agent: turns free-text trip requests into a structured
TripRequirements object.
"""

from pathlib import Path

import anthropic

from schemas.requirements import TripRequirements

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "requirements.md").read_text()

client = anthropic.Anthropic()


def analyze(free_text: str) -> TripRequirements:
    """Extract structured trip requirements from a free-text request.

    Args:
        free_text: the user's trip request, usually in Lithuanian, e.g.
            "Albanija, 3 dienos, spalio 2-4, 2 zmones, automobilis, ..."
    """
    response = client.messages.parse(
        model="claude-opus-5",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": free_text}],
        output_format=TripRequirements,
    )
    return response.parsed_output
