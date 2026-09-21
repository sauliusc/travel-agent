"""Shared helper for running a single agent turn via the Claude Code CLI.

Authenticates via Claude Code's own subscription login (`claude login`),
not an Anthropic API key -- `claude -p` (headless/print mode) is Claude
Code's own documented way for a subscriber to script their personal
usage, distinct from the separate Agent SDK library (which requires API
key billing and explicitly forbids subscription auth for built products).

Every concrete agent module is a thin wrapper around run_agent(): its own
system prompt (prompts/*.md) and its own allowed tools, nothing else.
Custom "tools" this project needs (OSRM, Overpass, Wikimedia, ...) are
plain CLI scripts under tools/ that an agent invokes via the Bash tool --
there is no Python-side tool-calling API here, unlike the old
Anthropic-SDK-based version.
"""

import json
import subprocess

CLAUDE_BIN = "claude"
DEFAULT_TIMEOUT = 600  # seconds


class ClaudeCLIError(RuntimeError):
    """Raised when the claude CLI exits non-zero or returns malformed output."""


def run_agent(
    system_prompt: str,
    allowed_tools: list[str],
    user_input: str,
    permission_mode: str = "auto",
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Run one agent turn via `claude -p` and return its text result.

    Args:
        system_prompt: appended as the agent's system prompt (from prompts/*.md)
        allowed_tools: tool names Claude Code may use without an interactive
            prompt, e.g. ["Bash", "WebSearch"]. A custom Python "tool" is
            invoked by the agent through Bash calling the matching
            tools/*.py script -- there's no separate tool-registration step.
        user_input: the task/input for this agent turn
        permission_mode: "auto" runs Claude Code's built-in risk classifier
            instead of interactive prompts; see `claude -p --help` for other
            modes (e.g. "dontAsk" also denies prompt-only tools outright)
        timeout: seconds to wait for the subprocess before raising
    """
    cmd = [
        CLAUDE_BIN,
        "-p",
        user_input,
        "--append-system-prompt",
        system_prompt,
        "--allowedTools",
        ",".join(allowed_tools),
        "--permission-mode",
        permission_mode,
        "--output-format",
        "json",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise ClaudeCLIError(
            "'claude' binary not found on PATH -- install Claude Code and run "
            "`claude login` (see docs/PROXMOX_SETUP.md)"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise ClaudeCLIError(f"claude did not finish within {timeout}s") from e

    if result.returncode != 0:
        raise ClaudeCLIError(
            f"claude exited {result.returncode}: "
            f"{(result.stderr or result.stdout).strip()[:2000]}"
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ClaudeCLIError(
            f"claude returned non-JSON stdout: {result.stdout[:500]!r}"
        ) from e

    text = payload.get("result")
    if text is None:
        raise ClaudeCLIError(f"claude JSON output missing 'result' field: {payload!r}")
    return text
