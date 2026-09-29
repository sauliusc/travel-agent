"""CI/CD agent: creates the trip's GitHub repository, pushes the page, its
verified images and workflows, and enables Pages.

This is deterministic plumbing (not model reasoning), so it calls the
tools/github.py functions directly rather than going through the Tool Runner.
"""

from pathlib import Path

from schemas.images import ImageResults
from tools.github import create_repo, enable_pages, push_file
from tools.image_download import cache_path

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

WORKFLOW_FILES = ["auto-merge.yml", "deploy.yml"]


def deploy(owner: str, repo_name: str, description: str, page_html: str, images: ImageResults) -> str:
    """Create a repo, push images + workflows + the page, and enable Pages.

    Args:
        owner: GitHub account/org to create the repo under
        repo_name: repository name, e.g. "ai-trip-albania-roundtrip"
        description: repository description
        page_html: the complete index.html content from the Page Designer agent
        images: verified manifest from tools/image_download.py; each entry's
            bytes are read from the local image cache and pushed at local_path
    """
    # public: GitHub Pages needs a public repo (without GitHub Enterprise),
    # and every trip repo this pipeline creates is meant to be served via
    # Pages right after this function's enable_pages() call below.
    log = [create_repo(name=repo_name, description=description, private=False)]

    # Images and workflows first, index.html last: every push to main triggers
    # deploy.yml, and the last push is the one whose build should win.
    for img in images.images:
        path = cache_path(img.local_path)
        if not path.is_file():
            log.append(f"Skipped {img.local_path}: not in local image cache ({path})")
            continue
        log.append(push_file(
            owner=owner, repo=repo_name, path=img.local_path, content=path.read_bytes(),
            message=f"chore: nuotrauka {img.stop_name}",
        ))

    for workflow in WORKFLOW_FILES:
        log.append(push_file(
            owner=owner, repo=repo_name, path=f".github/workflows/{workflow}",
            content=(TEMPLATES_DIR / workflow).read_text(), message=f"chore: {workflow}",
        ))

    log.append(enable_pages(owner=owner, repo=repo_name))
    index_result = push_file(owner=owner, repo=repo_name, path="index.html", content=page_html, message="feat: trip page")
    log.append(index_result)
    if index_result.startswith("Failed"):
        # Without index.html there is no page to link to -- fail the run
        # rather than report a published page that doesn't exist.
        raise RuntimeError("Puslapio nepavyko įkelti į GitHub:\n" + "\n".join(log))

    return "\n".join(log)


def page_url(owner: str, repo_name: str) -> str:
    """Public GitHub Pages URL of a trip repo."""
    return f"https://{owner}.github.io/{repo_name}/"
