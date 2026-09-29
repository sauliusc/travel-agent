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

import contextvars
import json
import os
import shutil
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path

DEFAULT_TIMEOUT = 600  # seconds

# No agent may write files: every agent's output is its answer, which the
# orchestrator persists and passes on. Agents run in the repo checkout, and a
# real Page Designer run used Write to save index.html into it, then returned
# a summary of what it did -- which was published as the trip page.
ALWAYS_DISALLOWED = ["Write", "Edit", "NotebookEdit"]

# Set by orchestrator.py (via log_calls()) around each stage's agent call so
# every real `claude -p` query+response can be persisted to the console DB
# (console/db.py's trip_agent_calls) instead of only being visible by
# grepping `ps aux`/journalctl on the box the pipeline runs on.
_call_sink: contextvars.ContextVar = contextvars.ContextVar("_call_sink", default=None)


class _CallSink:
    __slots__ = ("stage", "on_llm_call")

    def __init__(self, stage: str, on_llm_call):
        self.stage = stage
        self.on_llm_call = on_llm_call


@contextmanager
def log_calls(stage: str, on_llm_call=None):
    """While active, every _invoke_claude() call reports its query+raw
    response to on_llm_call(stage, query, response_text).

    A no-op (no context set) when on_llm_call is None, so this is safe to
    wrap around every call site unconditionally.
    """
    if on_llm_call is None:
        yield
        return
    token = _call_sink.set(_CallSink(stage, on_llm_call))
    try:
        yield
    finally:
        _call_sink.reset(token)

# Common install locations the official installer (claude.ai/install.sh) can
# use, checked if a bare "claude" isn't resolved via PATH. This matters most
# for the systemd service: the installer adds ~/.local/bin to PATH via
# .bashrc, which systemd units don't source -- confirmed on a real
# deployment where `claude` worked in an interactive shell but not under
# systemd. The unit file also sets PATH explicitly now; this is a second,
# independent line of defense in case that ever drifts out of sync again.
_FALLBACK_CLAUDE_PATHS = [
    Path.home() / ".local" / "bin" / "claude",
    Path("/usr/local/bin/claude"),
]


def _resolve_claude_bin() -> str:
    override = os.environ.get("CLAUDE_BIN")
    if override:
        return override
    found = shutil.which("claude")
    if found:
        return found
    for candidate in _FALLBACK_CLAUDE_PATHS:
        if candidate.is_file():
            return str(candidate)
    return "claude"  # let subprocess.run raise FileNotFoundError with a clear message


def _transcript_tail(session_id: str, limit: int = 25) -> str:
    """Last tool calls/results from Claude Code's own session transcript.

    A timed-out `claude -p` is killed before it prints anything, so without
    this the console only shows "did not finish within Ns" -- this is what
    it was actually doing (on a real run: parallel Overpass calls each
    stalling past the Bash tool's 120s limit).
    """
    matches = list((Path.home() / ".claude" / "projects").glob(f"*/{session_id}.jsonl"))
    if not matches:
        return "(no session transcript found)"
    lines = []
    for raw in matches[0].read_text(errors="replace").splitlines():
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        ts = entry.get("timestamp", "")[11:19]
        content = (entry.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                inp = block.get("input") or {}
                lines.append(f"{ts} CALL   {str(inp.get('command', inp))[:300]}")
            elif block.get("type") == "tool_result":
                body = block.get("content")
                body = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
                lines.append(f"{ts} RESULT {body[:300]}".replace("\n", " "))
    return "\n".join(lines[-limit:]) or "(transcript has no tool calls)"


class ClaudeCLIError(RuntimeError):
    """Raised when the claude CLI exits non-zero or returns malformed output."""


def _invoke_claude(
    system_prompt: str,
    allowed_tools: list[str],
    user_input: str,
    permission_mode: str = "auto",
    timeout: int = DEFAULT_TIMEOUT,
    extra_args: list[str] | None = None,
    disallowed_tools: list[str] | None = None,
) -> dict:
    """Run `claude -p` and return its full parsed JSON payload.

    Shared by run_agent() (plain text agents) and requirements.py's
    schema-validated extraction (which also needs the raw payload to read
    a structured-output field, not just "result").
    """
    session_id = str(uuid.uuid4())
    cmd = [
        _resolve_claude_bin(),
        "-p",
        user_input,
        "--append-system-prompt",
        system_prompt,
        "--allowedTools",
        ",".join(allowed_tools),
        "--disallowedTools",
        ",".join(ALWAYS_DISALLOWED + (disallowed_tools or [])),
        "--permission-mode",
        permission_mode,
        "--output-format",
        "json",
        "--session-id",
        session_id,
        *(extra_args or []),
    ]

    # What actually gets sent, formatted for a human reading it back later
    # (the console UI) rather than for re-execution -- system prompt and
    # user input are the two parts worth reading, the flags are secondary.
    query = (
        f"[system prompt]\n{system_prompt}\n\n"
        f"[user input]\n{user_input}\n\n"
        f"[cli] --allowedTools {','.join(allowed_tools)} --permission-mode {permission_mode}"
        + (f" {' '.join(extra_args)}" if extra_args else "")
    )

    def _record(response_text: str) -> None:
        sink = _call_sink.get()
        if sink is not None:
            sink.on_llm_call(sink.stage, query, response_text)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        _record("ERROR: 'claude' binary not found on PATH")
        raise ClaudeCLIError(
            "'claude' binary not found on PATH -- install Claude Code and run "
            "`claude auth login` (see docs/PROXMOX_SETUP.md)"
        ) from e
    except subprocess.TimeoutExpired as e:
        _record(
            f"ERROR: claude did not finish within {timeout}s\n\n"
            f"Last tool activity (session {session_id}):\n{_transcript_tail(session_id)}"
        )
        raise ClaudeCLIError(f"claude did not finish within {timeout}s") from e

    if result.returncode != 0:
        err_text = (result.stderr or result.stdout).strip()[:2000]
        _record(f"ERROR: claude exited {result.returncode}: {err_text}")
        raise ClaudeCLIError(f"claude exited {result.returncode}: {err_text}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        _record(f"ERROR: claude returned non-JSON stdout: {result.stdout[:500]!r}")
        raise ClaudeCLIError(
            f"claude returned non-JSON stdout: {result.stdout[:500]!r}"
        ) from e

    # Full raw JSON response (not just "result"), so a structured-output
    # call (e.g. requirements.py, images.py) still shows something useful
    # even when "result" itself is empty/absent.
    _record(result.stdout)
    return payload


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
    payload = _invoke_claude(system_prompt, allowed_tools, user_input, permission_mode, timeout)
    text = payload.get("result")
    if text is None:
        raise ClaudeCLIError(f"claude JSON output missing 'result' field: {payload!r}")
    return text


def run_structured(
    system_prompt: str,
    allowed_tools: list[str],
    user_input: str,
    model,
    timeout: int = DEFAULT_TIMEOUT,
    disallowed_tools: list[str] | None = None,
):
    """Run one agent turn with --json-schema for a Pydantic `model` and return
    the validated instance (structured_output first, then "result" as JSON)."""
    payload = _invoke_claude(
        system_prompt, allowed_tools, user_input, timeout=timeout,
        extra_args=["--json-schema", json.dumps(model.model_json_schema())],
        disallowed_tools=disallowed_tools,
    )
    structured = payload.get("structured_output")
    if structured is not None:
        return model.model_validate(structured)
    text = payload.get("result")
    if text is None:
        raise ClaudeCLIError(f"claude JSON output missing both 'structured_output' and 'result': {payload!r}")
    try:
        return model.model_validate_json(text)
    except Exception as e:
        raise ClaudeCLIError(f"agent did not return a valid {model.__name__}: {text[:500]!r}") from e
