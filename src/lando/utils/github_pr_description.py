from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import escape

from lando.api.legacy.commit_message import parse_bugs
from lando.main.models import (
    Repo,
)
from lando.main.models.landing_job import (
    get_pull_request_last_landing_job_status,
)
from lando.utils.github import (
    PR_DELIMITER,
)
from lando.utils.github_checks import (
    ALL_PULL_REQUEST_BLOCKERS,
    ALL_PULL_REQUEST_WARNINGS,
    PullRequestChecks,
)
from lando.utils.github_helpers import (
    LandoPullRequest,
    PullRequestPatchHelper,
)
from lando.utils.landing_checks import LandingChecks


def generate_warnings_and_blockers(
    target_repo: Repo,
    pull_request: LandoPullRequest,
    request: HttpRequest,
    do_escape: bool = True,
) -> dict[str, list[str]]:
    """Run checks on a pull request and return blockers and warnings."""
    # PullRequestPatchHelper.diff doesn't include binary changes.
    # This is not considered an issue for checks at the moment, but may need to be kept in
    # mind for the future.
    patch_helper = PullRequestPatchHelper(pull_request)
    author_email = pull_request.author[1]
    landing_checks = LandingChecks(author_email, target_repo.name)
    blockers = landing_checks.run(
        target_repo.hooks,
        [patch_helper],
    )
    pr_checks = PullRequestChecks(pull_request.client, target_repo, request)
    pr_blockers = [chk.name() for chk in ALL_PULL_REQUEST_BLOCKERS]
    blockers += pr_checks.run(pr_blockers, pull_request)
    pr_warnings = [chk.name() for chk in ALL_PULL_REQUEST_WARNINGS]
    warnings = pr_checks.run(pr_warnings, pull_request)

    if do_escape:
        # Sanitize blockers and warnings as they may be rendered in a page.
        warnings = [escape(warning) for warning in warnings]
        blockers = [escape(blocker) for blocker in blockers]

    return {"warnings": warnings, "blockers": blockers}


def generate_enhanced_pr_description(
    pull_request: LandoPullRequest,
    target_repo: Repo,
    request: WSGIRequest | None = None,
    template: str = "pr_description.md",
) -> str:
    context = {}
    if request:
        context.update(
            generate_warnings_and_blockers(target_repo, pull_request, request)
        )

    landing_status = get_pull_request_last_landing_job_status(
        target_repo, pull_request.number
    )
    context["landing_status"] = (
        landing_status.label.lower() if landing_status else "unknown"
    )

    path = reverse(
        "pull-request",
        kwargs={
            "repo_name": target_repo.name,
            "number": pull_request.number,
        },
    )

    context["lando_url"] = f"{settings.SITE_URL}{path}"
    context["pr_delimiter"] = PR_DELIMITER
    bugs = parse_bugs(pull_request.title)
    context["bugs"] = bugs
    context["title"] = pull_request.title
    context["commit_body"] = pull_request.commit_body

    rendered = render_to_string(template, context)
    return rendered
