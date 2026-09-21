"""Centralized credential loading and validation.

Every secret the system needs lives in exactly one place: environment
variables, optionally populated from a dotenv-style file (see
.env.example). This module owns finding that file and checking what's
missing — so a misconfigured deploy fails loudly at startup with one
clear message, instead of a KeyError or a mysterious claude CLI error
three agents deep into a run.

Anthropic access is no longer a credential this project manages itself:
agents run through the Claude Code CLI on subscription auth
(`claude auth login`), not an API key, so there is nothing to load for
it here -- only to check. `claude auth status --json` is the verified
way to check that (confirmed against the real installed CLI; its exact
output shape is {"loggedIn": bool, "authMethod": str, "apiProvider": str,
"configDirectory": str}).

No external dependency (no python-dotenv) -- the format is deliberately
trivial (KEY=VALUE, # comments, blank lines) so hand-parsing it is simpler
than adding a package for it.
"""

import json
import os
import subprocess
from pathlib import Path

# Checked in order; the first file that exists is loaded. A real env var
# (e.g. set by a systemd EnvironmentFile=) always wins over either of these.
CREDENTIALS_FILES = [
    Path("/etc/travel-agent/credentials.env"),  # Proxmox/systemd install (scripts/install.sh)
    Path(__file__).parent.parent / ".env",  # local dev
]


def _load_dotenv_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not value:
            continue
        os.environ.setdefault(key, value)


def load_credentials() -> None:
    """Populate os.environ from the first existing credentials file, if any."""
    for path in CREDENTIALS_FILES:
        _load_dotenv_file(path)


def _check_claude_auth() -> str | None:
    """Return None if `claude` is authenticated, else a human-readable problem."""
    try:
        result = subprocess.run(
            ["claude", "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return (
            "'claude' binary not found on PATH -- install Claude Code and run "
            "`claude auth login` (see docs/PROXMOX_SETUP.md)"
        )
    except subprocess.TimeoutExpired:
        return "`claude auth status` did not respond within 15s"

    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError:
        return f"`claude auth status --json` returned non-JSON output: {result.stdout[:300]!r}"

    if not status.get("loggedIn"):
        return "Not logged into Claude Code -- run `claude auth login` (subscription sign-in)"

    return None


def require_credentials() -> list[str]:
    """Load credentials, then return a list of human-readable problems.

    An empty list means everything needed to run a full trip is present.
    Call this once at process startup (console/app.py does).
    """
    load_credentials()
    problems = []

    claude_problem = _check_claude_auth()
    if claude_problem:
        problems.append(claude_problem)

    if not os.environ.get("GITHUB_TOKEN"):
        problems.append(
            "GITHUB_TOKEN is not set — the CI/CD agent needs it to create repos and push files."
        )
    if not os.environ.get("GITHUB_OWNER"):
        os.environ["GITHUB_OWNER"] = "sauliusc"

    return problems
