"""CI/CD agent: creates the trip's GitHub repository, pushes the page and
workflows, enables Pages, and triggers the image-fetch workflow.

This is deterministic plumbing (not model reasoning), so it calls the
tools/github.py functions directly rather than going through the Tool Runner.
"""

from pathlib import Path

from tools.github import create_repo, enable_pages, push_file, trigger_workflow

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

WORKFLOW_FILES = ["auto-merge.yml", "deploy.yml", "fetch-images.yml"]


def deploy(owner: str, repo_name: str, description: str, page_html: str, images_summary: str) -> str:
    """Create a repo, push the page + workflows, enable Pages, trigger image fetch.

    Args:
        owner: GitHub account/org to create the repo under
        repo_name: repository name, e.g. "albania-3days-trip-v2"
        description: repository description
        page_html: the complete index.html content from the Page Designer agent
        images_summary: the Image agent's raw output (Commons file titles found
            per stop). Not yet parsed into the fetch-images.yml file list —
            embedded as a comment for now (see NOTE below and issue #14 follow-up).
    """
    log = [create_repo.func(name=repo_name, description=description, private=True)]

    log.append(push_file.func(owner=owner, repo=repo_name, path="index.html", content=page_html, message="feat: initial trip page"))

    auto_merge_yml = (TEMPLATES_DIR / "auto-merge.yml").read_text()
    deploy_yml = (TEMPLATES_DIR / "deploy.yml").read_text()
    log.append(
        push_file.func(
            owner=owner, repo=repo_name, path=".github/workflows/auto-merge.yml",
            content=auto_merge_yml, message="chore: auto-merge workflow",
        )
    )
    log.append(
        push_file.func(
            owner=owner, repo=repo_name, path=".github/workflows/deploy.yml",
            content=deploy_yml, message="chore: deploy workflow",
        )
    )
    fetch_images_template = (TEMPLATES_DIR / "fetch-images.yml").read_text()
    # NOTE: images_summary is currently free text from the Image agent, not a
    # structured (local_path, commons_filename) list — this embeds it as a
    # comment so a human (or a future structured-output pass on the Image
    # agent) can fill in the `files = [...]` list. Not yet auto-populated.
    commented_summary = "\n".join(f"          # {line}" for line in images_summary.splitlines())
    fetch_images_yml = fetch_images_template.replace(
        "# IMAGES_PLACEHOLDER", f"# TODO: fill in from Image agent output below\n{commented_summary}"
    )
    log.append(
        push_file.func(
            owner=owner, repo=repo_name, path=".github/workflows/fetch-images.yml",
            content=fetch_images_yml, message="chore: fetch-images workflow",
        )
    )

    log.append(enable_pages.func(owner=owner, repo=repo_name))
    log.append(trigger_workflow.func(owner=owner, repo=repo_name, workflow_file="fetch-images.yml"))

    return "\n".join(log)
