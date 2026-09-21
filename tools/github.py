"""GitHub REST API helpers for the CI/CD agent: create a repo, push files,
enable Pages, and trigger a workflow.

Requires a fine-grained personal access token with Contents, Pull requests,
Workflows, and Pages read/write permissions, passed via the GITHUB_TOKEN
environment variable (see docs/PROXMOX_SETUP.md).
"""

import base64
import os

import httpx
from anthropic import beta_tool

API_URL = "https://api.github.com"


def _headers() -> dict:
    token = os.environ["GITHUB_TOKEN"]
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@beta_tool
def create_repo(name: str, description: str = "", private: bool = True) -> str:
    """Create a new GitHub repository under the authenticated user's account.

    Args:
        name: repository name, e.g. "albania-3days-trip-v2"
        description: short repository description
        private: whether the repo should be private (default True)
    """
    resp = httpx.post(
        f"{API_URL}/user/repos",
        headers=_headers(),
        json={"name": name, "description": description, "private": private, "auto_init": True},
        timeout=30,
    )
    if resp.status_code >= 400:
        return f"Failed to create repo '{name}': {resp.status_code} {resp.text}"
    data = resp.json()
    return f"Created {data['full_name']} at {data['html_url']}"


@beta_tool
def push_file(owner: str, repo: str, path: str, content: str, message: str, branch: str = "main") -> str:
    """Create or update a single file in a repository via the Contents API.

    Args:
        owner: repository owner
        repo: repository name
        path: file path within the repo, e.g. "index.html"
        content: full file content (text)
        message: commit message
        branch: target branch (default "main")
    """
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    # Look up the existing file's SHA (needed to update, not needed to create).
    get_resp = httpx.get(
        f"{API_URL}/repos/{owner}/{repo}/contents/{path}",
        headers=_headers(),
        params={"ref": branch},
        timeout=30,
    )
    sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None

    payload = {"message": message, "content": encoded, "branch": branch}
    if sha:
        payload["sha"] = sha

    put_resp = httpx.put(
        f"{API_URL}/repos/{owner}/{repo}/contents/{path}",
        headers=_headers(),
        json=payload,
        timeout=30,
    )
    if put_resp.status_code >= 400:
        return f"Failed to push {path}: {put_resp.status_code} {put_resp.text}"
    return f"Pushed {path} to {owner}/{repo}@{branch}"


@beta_tool
def enable_pages(owner: str, repo: str) -> str:
    """Enable GitHub Pages for a repository, sourced from GitHub Actions.

    Args:
        owner: repository owner
        repo: repository name
    """
    resp = httpx.post(
        f"{API_URL}/repos/{owner}/{repo}/pages",
        headers=_headers(),
        json={"build_type": "workflow"},
        timeout=30,
    )
    if resp.status_code >= 400:
        return f"Failed to enable Pages: {resp.status_code} {resp.text}"
    return f"Pages enabled for {owner}/{repo}: https://{owner}.github.io/{repo}/"


@beta_tool
def trigger_workflow(owner: str, repo: str, workflow_file: str, ref: str = "main") -> str:
    """Trigger a workflow_dispatch run for a given workflow file.

    Args:
        owner: repository owner
        repo: repository name
        workflow_file: workflow filename, e.g. "fetch-images.yml"
        ref: branch to run the workflow on (default "main")
    """
    resp = httpx.post(
        f"{API_URL}/repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches",
        headers=_headers(),
        json={"ref": ref},
        timeout=30,
    )
    if resp.status_code >= 400:
        return f"Failed to trigger {workflow_file}: {resp.status_code} {resp.text}"
    return f"Triggered {workflow_file} on {owner}/{repo}@{ref}"
