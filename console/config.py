"""Centralized credential loading and validation.

Every secret the system needs (Anthropic, GitHub, console basic auth) lives
in exactly one place: environment variables, optionally populated from a
dotenv-style file (see .env.example). This module owns finding that file
and checking what's missing — so a misconfigured deploy fails loudly at
startup with one clear message, instead of a KeyError three agents deep
into a run.

No external dependency (no python-dotenv) — the format is deliberately
trivial (KEY=VALUE, # comments, blank lines) so hand-parsing it is simpler
than adding a package for it.
"""

import os
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


def _has_anthropic_credentials() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    # `ant auth login` stores a profile here; its mere presence is enough —
    # the anthropic SDK reads it on its own, no env var needed.
    return (Path.home() / ".config" / "anthropic").exists()


def require_credentials() -> list[str]:
    """Load credentials, then return a list of human-readable problems.

    An empty list means everything needed to run a full trip is present.
    Call this once at process startup (console/app.py does).
    """
    load_credentials()
    problems = []

    if not _has_anthropic_credentials():
        problems.append(
            "No Anthropic credentials found: set ANTHROPIC_API_KEY or run `ant auth login`."
        )
    if not os.environ.get("GITHUB_TOKEN"):
        problems.append(
            "GITHUB_TOKEN is not set — the CI/CD agent needs it to create repos and push files."
        )
    if not os.environ.get("GITHUB_OWNER"):
        os.environ["GITHUB_OWNER"] = "sauliusc"

    return problems
