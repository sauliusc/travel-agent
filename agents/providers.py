"""External AI providers an agent can run on instead of native `claude -p`.

Configured in the console (⚙️ Nustatymai → AI tiekėjai) and chosen per agent.
agents/base.py routes a call here when the agent's stage has a provider; the
result is returned in the same shape as `claude -p --output-format json`
("result", "structured_output", "modelUsage"), so agents don't change.

What an external model can't do: run Claude Code's Bash tool -- agents that
call tools/*.py scripts (Logistics, Image, Weather, Food, Plan B) stay on
native Claude (see BASH_AGENTS). WebSearch/WebFetch map to Gemini's Google
Search grounding and URL context; OpenAI-compatible endpoints get no web tools.
"""

import contextvars
import json
import re
from contextlib import contextmanager
from typing import Callable

import httpx

# Agents whose work depends on running project tools through Bash.
BASH_AGENTS = {"logistics_report", "images", "weather", "food", "plan_b"}

PROVIDER_TYPES = {
    "gemini": "Google Gemini (API raktas)",
    "openai": "OpenAI-suderinamas (/chat/completions)",
}

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Set by the console: stage -> provider dict ({type, model, api_key, base_url, name}) or None.
_resolver: Callable[[str, int | None], dict | None] | None = None

# Agent set (rinkinys) of the trip being run; None = the base set.
_profile: contextvars.ContextVar = contextvars.ContextVar("_profile", default=None)


def set_resolver(fn: Callable[[str, int | None], dict | None] | None) -> None:
    global _resolver
    _resolver = fn


@contextmanager
def using_profile(profile_id: int | None):
    """Run the enclosed pipeline with this agent set's provider choices."""
    token = _profile.set(profile_id)
    try:
        yield
    finally:
        _profile.reset(token)


def provider_for(stage: str | None) -> dict | None:
    if stage is None or _resolver is None or stage in BASH_AGENTS:
        return None
    return _resolver(stage, _profile.get())


class ProviderError(RuntimeError):
    pass


def _json_instruction(schema: dict) -> str:
    return ("\n\nReply with ONLY one JSON object (no prose, no code fences) that validates against "
            f"this JSON Schema:\n{json.dumps(schema, ensure_ascii=False)}")


def _extract_json(text: str):
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = fenced.group(1) if fenced else text
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        raise ProviderError(f"model did not return JSON: {text[:300]!r}")
    return json.loads(body[start:end + 1])


def _gemini(p: dict, system_prompt: str, user_input: str, web: bool, fetch: bool,
            schema: dict | None, timeout: int) -> tuple[str, dict]:
    tools = ([{"google_search": {}}] if web else []) + ([{"url_context": {}}] if fetch else [])
    gen = {}
    if schema is not None and not tools:  # JSON mode can't be combined with grounding
        gen["responseMimeType"] = "application/json"
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_input + (_json_instruction(schema) if schema else "")}]}],
        **({"tools": tools} if tools else {}),
        **({"generationConfig": gen} if gen else {}),
    }
    # Key in a header, not the URL, so it never shows up in logged URLs.
    resp = httpx.post(GEMINI_URL.format(model=p["model"]), headers={"x-goog-api-key": p["api_key"]},
                      json=body, timeout=timeout)
    if resp.status_code != 200:
        raise ProviderError(f"Gemini HTTP {resp.status_code}: {resp.text[:400]}")
    data = resp.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError):
        raise ProviderError(f"Gemini returned no answer: {json.dumps(data)[:400]}")
    return "".join(part.get("text", "") for part in parts), data.get("usageMetadata", {})


def _openai(p: dict, system_prompt: str, user_input: str, schema: dict | None, timeout: int) -> tuple[str, dict]:
    body = {
        "model": p["model"],
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_input + (_json_instruction(schema) if schema else "")}],
        **({"response_format": {"type": "json_object"}} if schema else {}),
    }
    url = (p.get("base_url") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    resp = httpx.post(url, headers={"Authorization": f"Bearer {p['api_key']}"}, json=body, timeout=timeout)
    if resp.status_code != 200:
        raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:400]}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"] or "", data.get("usage", {})
    except (KeyError, IndexError):
        raise ProviderError(f"no answer: {json.dumps(data)[:400]}")


def call(p: dict, system_prompt: str, user_input: str, allowed_tools: list[str],
         schema: dict | None, timeout: int) -> dict:
    """One agent turn on an external provider, as a claude-style JSON payload."""
    try:
        if p["type"] == "gemini":
            text, usage = _gemini(p, system_prompt, user_input, "WebSearch" in allowed_tools,
                                  "WebFetch" in allowed_tools, schema, timeout)
        elif p["type"] == "openai":
            text, usage = _openai(p, system_prompt, user_input, schema, timeout)
        else:
            raise ProviderError(f"unknown provider type {p['type']!r}")
    except httpx.HTTPError as e:
        raise ProviderError(f"{type(e).__name__}: {e}") from e
    payload = {"result": text, "is_error": False, "num_turns": 1,
               "modelUsage": {f"{p['model']} ({p.get('name') or p['type']})": usage}}
    if schema is not None:
        payload["structured_output"] = _extract_json(text)
    return payload
