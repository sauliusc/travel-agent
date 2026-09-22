"""CI/CD agent: creates the trip's GitHub repository, pushes the page and
workflows, enables Pages, and triggers the image-fetch workflow.

This is deterministic plumbing (not model reasoning), so it calls the
tools/github.py functions directly rather than going through the Tool Runner.
"""

from pathlib import Path

from schemas.images import ImageResults
from tools.github import create_repo, enable_pages, push_file, trigger_workflow

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

WORKFLOW_FILES = ["auto-merge.yml", "deploy.yml", "fetch-images.yml"]

# Only these license families are safe to redistribute via the generated
# fetch-images.yml -- matches the Image agent's own prompt instructions, but
# enforced again here since this is the step that actually ships the files.
_ALLOWED_LICENSE_PREFIXES = ("cc by", "cc-by", "public domain", "cc0")


def _render_files_list(images: ImageResults) -> str:
    accepted = []
    skipped = []
    for img in images.images:
        if img.license.strip().lower().startswith(_ALLOWED_LICENSE_PREFIXES):
            accepted.append(img)
        else:
            skipped.append(img)

    lines = [
        f"            ('{img.local_path}', '{img.commons_filename}'),  # {img.stop_name}"
        for img in accepted
    ]
    if skipped:
        lines.append("            # Skipped (license not in the allowed set):")
        for img in skipped:
            lines.append(f"            # {img.stop_name}: {img.commons_filename} ({img.license})")
    return "\n".join(lines)


def deploy(owner: str, repo_name: str, description: str, page_html: str, images: ImageResults) -> str:
    """Create a repo, push the page + workflows, enable Pages, trigger image fetch.

    Args:
        owner: GitHub account/org to create the repo under
        repo_name: repository name, e.g. "albania-3days-trip-v2"
        description: repository description
        page_html: the complete index.html content from the Page Designer agent
        images: structured Image agent output (agents/images.py), rendered
            directly into fetch-images.yml's files = [...] list
    """
    log = [create_repo(name=repo_name, description=description, private=True)]

    log.append(push_file(owner=owner, repo=repo_name, path="index.html", content=page_html, message="feat: initial trip page"))

    auto_merge_yml = (TEMPLATES_DIR / "auto-merge.yml").read_text()
    deploy_yml = (TEMPLATES_DIR / "deploy.yml").read_text()
    log.append(
        push_file(
            owner=owner, repo=repo_name, path=".github/workflows/auto-merge.yml",
            content=auto_merge_yml, message="chore: auto-merge workflow",
        )
    )
    log.append(
        push_file(
            owner=owner, repo=repo_name, path=".github/workflows/deploy.yml",
            content=deploy_yml, message="chore: deploy workflow",
        )
    )
    fetch_images_template = (TEMPLATES_DIR / "fetch-images.yml").read_text()
    fetch_images_yml = fetch_images_template.replace(
        "# IMAGES_PLACEHOLDER", _render_files_list(images)
    )
    log.append(
        push_file(
            owner=owner, repo=repo_name, path=".github/workflows/fetch-images.yml",
            content=fetch_images_yml, message="chore: fetch-images workflow",
        )
    )

    log.append(enable_pages(owner=owner, repo=repo_name))
    log.append(trigger_workflow(owner=owner, repo=repo_name, workflow_file="fetch-images.yml"))

    return "\n".join(log)
