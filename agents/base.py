"""Shared helper for running a single agent turn via the Tool Runner.

Every concrete agent (logistics, itinerary, critic, ...) is a thin wrapper
around run_agent(): its own system prompt + its own tools, nothing else.
"""

import anthropic

client = anthropic.Anthropic()

DEFAULT_MODEL = "claude-opus-5"


def run_agent(
    system_prompt: str,
    tools: list,
    user_input: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 16000,
) -> str:
    """Run one agent to completion and return its final text response.

    Args:
        system_prompt: the agent's system prompt (loaded from prompts/*.md)
        tools: list of @beta_tool functions, and/or server-tool dicts
        user_input: the task/input for this agent turn
        model: Claude model id (default claude-opus-5)
        max_tokens: response token cap
    """
    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        tools=tools,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": user_input}],
    )
    last = None
    for message in runner:
        last = message
    if last is None:
        raise RuntimeError("Agent produced no response")
    return "".join(block.text for block in last.content if block.type == "text")
