import logging
import re
import urllib.parse
from typing import Optional

from compressor.contrib.jinja2ext import CompressorExtension
from django.conf import settings
from django.contrib import messages
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import escape
from jinja2 import Environment

from lando.main.models import JobStatus, LandingJob, Repo, UpliftJob
from lando.main.scm import SCM_TYPE_GIT
from lando.treestatus.models import (
    ReasonCategory,
    TreeCategory,
)
from lando.ui.legacy.forms import UserSettingsForm

FAQ_URL = "https://wiki.mozilla.org/Phabricator/FAQ#Lando"
SEC_BUG_DOCS = "https://firefox-source-docs.mozilla.org/bug-mgmt/processes/security-approval.html"  # noqa: E501

logger = logging.getLogger(__name__)


def escape_html(text: str) -> str:
    return escape(text)


def tostatusbadgeclass(landing_job: LandingJob) -> str:
    mapping = {
        "aborted": "Badge Badge--negative",
        "submitted": "Badge Badge--warning",
        "in_progress": "Badge Badge--warning",
        "landed": "Badge Badge--positive",
        "failed": "Badge Badge--negative",
    }
    return mapping.get(landing_job.status.lower(), "Badge Badge--negative")


def reviewer_to_status_badge_class(reviewer: dict) -> str:
    return {
        # status: (current_diff, for_other_diff),
        "accepted": ("Badge Badge--positive", "Badge Badge--neutral"),
        "rejected": ("Badge Badge--negative", "Badge Badge--warning"),
        "added": ("Badge", "Badge"),
        "blocking": ("Badge", "Badge"),
        "resigned": ("Badge", "Badge"),
    }.get(reviewer["status"], ("Badge Badge--warning", "Badge Badge--warning"))[
        1 if reviewer["for_other_diff"] else 0
    ]


def treestatus_to_status_badge_class(tree_status: str) -> str:
    """Convert Tree statuses into status badges."""
    return {
        "open": "Badge Badge--positive",
        "closed": "Badge Badge--negative",
        "approval required": "Badge Badge--warning",
    }.get(tree_status, "Badge Badge--warning")


def reviewer_to_action_text(reviewer: dict) -> str:
    options = {
        # status: (current_diff, for_other_diff),
        "accepted": ("accepted", "accepted a prior diff"),
        "rejected": ("requested changes", "requested changes to a prior diff"),
        "added": ("to review", "to review"),
        "blocking": ("must review", "must review"),
        "resigned": ("resigned", "resigned"),
    }.get(reviewer["status"], ("UNKNOWN STATE", "UNKNOWN STATE"))
    return options[1 if reviewer["for_other_diff"] else 0]


def revision_status_to_badge_class(status: str) -> str:
    return {
        "abandoned": "Badge",
        "accepted": "Badge Badge--positive",
        "changes-planned": "Badge Badge--neutral",
        "published": "Badge",
        "needs-review": "Badge Badge--warning",
        "needs-revision": "Badge Badge--negative",
        "draft": "Badge Badge--neutral",
    }.get(status, "Badge Badge--warning")


def tostatusbadgename(landing_job: LandingJob) -> str:
    mapping = {
        "aborted": "Aborted",
        "submitted": "Landing queued",
        "in_progress": "In progress",
        "landed": "Successfully landed",
        "failed": "Failed to land",
    }
    return mapping.get(landing_job.status.lower(), landing_job.status.capitalize())


def uplift_status_tag_class(job: UpliftJob) -> str:
    try:
        status = JobStatus(job.status)
    except ValueError:
        status = None

    if status == JobStatus.LANDED:
        return "is-success"
    if status == JobStatus.FAILED:
        return "is-danger"
    if status == JobStatus.IN_PROGRESS:
        return "is-info"
    if status == JobStatus.DEFERRED:
        return "is-warning"
    return "is-light"


def uplift_status_icon_class(job: UpliftJob) -> str:
    try:
        status = JobStatus(job.status)
    except ValueError:
        status = None

    if status == JobStatus.LANDED:
        return "fa fa-check"
    if status == JobStatus.FAILED:
        return "fa fa-times"
    if status == JobStatus.IN_PROGRESS:
        return "fa fa-clock-o"
    if status == JobStatus.DEFERRED:
        return "fa fa-history"
    if status == JobStatus.CREATED:
        return "fa fa-file-o"
    if status == JobStatus.SUBMITTED:
        return "fa fa-hourglass-start"
    if status == JobStatus.CANCELLED:
        return "fa fa-ban"
    return ""


def uplift_status_label(job: UpliftJob) -> str:
    try:
        status = JobStatus(job.status)
    except ValueError:
        return ""

    if status == JobStatus.LANDED:
        return "Requested revisions apply cleanly to uplift branch; uplift revisions created"

    return status.label


def reason_category_to_display(reason_category_str: str) -> str:
    try:
        return ReasonCategory(reason_category_str).label
    except ValueError:
        # Return the bare string, in case of older data.
        return reason_category_str


def tree_category_to_display(tree_category_str: str) -> str:
    try:
        return TreeCategory(tree_category_str).label
    except ValueError:
        return tree_category_str


def avatar_url(url: str) -> str:
    # If a user doesn't have a gravatar image for their auth0 email address,
    # gravatar uses auth0's provided default which redirects to
    # *.wp.com/cdn.auth0.com/. Instead of whitelisting this in our CSP,
    # here, we opt into a default generated image provided by gravatar.
    try:
        parsed_url = urllib.parse.urlsplit(url)
        if not parsed_url.netloc:
            raise ValueError("Avatar URLs should not be relative")
    except (AttributeError, ValueError):
        logger.debug("Invalid avatar url provided", extra={"url": url})
        return ""

    if parsed_url.netloc in ("s.gravatar.com", "www.gravatar.com"):
        query = urllib.parse.parse_qs(parsed_url.query)
        query["d"] = "identicon"
        parsed_url = (
            parsed_url[:3]
            + (urllib.parse.urlencode(query, doseq=True),)
            + parsed_url[4:]
        )

    return urllib.parse.urlunsplit(parsed_url)


def linkify_bug_numbers(text: str) -> str:
    search = r"(?=\b)(Bug (\d+))(?=\b)"
    replace = r'<a href="{bmo_url}/show_bug.cgi?id=\g<2>">\g<1></a>'.format(
        bmo_url=settings.BUGZILLA_URL
    )
    return re.sub(search, replace, str(text), flags=re.IGNORECASE)


def linkify_revision_urls(text: str) -> str:
    search = r"(?=\b)(" + re.escape(settings.PHABRICATOR_URL) + r"/D\d+)(?=\b)"
    replace = r'<a href="\g<1>">\g<1></a>'
    return re.sub(search, replace, str(text), flags=re.IGNORECASE)


def linkify_revision_ids(text: str) -> str:
    """Linkify revision IDs to proper Phabricator URLs."""
    search = r"\b(D\d+)\b"
    replace = (
        rf'<a href="{settings.PHABRICATOR_URL}/\g<1>" ' r'target="_blank">\g<1></a>'
    )
    return re.sub(search, replace, str(text), flags=re.IGNORECASE)


def linkify_transplant_details(text: str, landing_job: LandingJob) -> str:
    # The transplant result is not always guaranteed to be a commit id. It
    # can be a message saying that the landing was queued and will land later.
    if landing_job.status != JobStatus.LANDED:
        return text

    search = r"(?=\b)(" + re.escape(landing_job.landed_commit_id) + r")(?=\b)"

    # We assume HG by default (legacy path), but use a Github-like path if 'git' is
    # present in the netloc.
    link_template = r'<a href="{repo_url}/rev/\g<1>">\g<1></a>'
    if landing_job.target_repo.scm_type == SCM_TYPE_GIT:
        link_template = r'<a href="{repo_url}/commit/\g<1>">\g<1></a>'

    replace = link_template.format(repo_url=landing_job.target_repo.normalized_url)
    return re.sub(search, replace, str(text))  # This is case sensitive


def treeherder_link(treeherder_revision: str, label: str = "") -> str:
    """Builds a Treeherder link for a given revision."""

    if not treeherder_revision:
        return "[Failed to determine Treeherder revision]"

    label = label or treeherder_revision

    return f'<a href="{settings.TREEHERDER_URL}/jobs?revision={treeherder_revision}">{label}</a>'


def linkify_faq(text: str) -> str:
    search = r"\b(FAQ)\b"
    replace = r'<a href="{faq_url}">\g<1></a>'.format(faq_url=FAQ_URL)
    return re.sub(search, replace, str(text), flags=re.IGNORECASE)


def linkify_sec_bug_docs(text: str) -> str:
    search = r"\b(Security Bug Approval Process)\b"
    replace = r'<a href="{docs_url}">\g<1></a>'.format(docs_url=SEC_BUG_DOCS)
    return re.sub(search, replace, str(text), flags=re.IGNORECASE)


def bug_url(text: str) -> str:
    return "{bmo_url}/show_bug.cgi?id={bug_number}".format(
        bmo_url=settings.BUGZILLA_URL, bug_number=text
    )


def revision_url(revision_id: int | str, diff_id: Optional[str] = None) -> str:
    if isinstance(revision_id, int):
        path = f"D{revision_id}"
    elif isinstance(revision_id, str) and not revision_id.startswith("D"):
        path = f"D{revision_id}"
    else:
        path = revision_id

    url = "{phab_url}/{path}".format(phab_url=settings.PHABRICATOR_URL, path=path)
    if diff_id is not None and diff_id != "":
        url = "{revision_url}?id={diff_id}".format(revision_url=url, diff_id=diff_id)

    return url


def repo_path(repo_url: str) -> str:
    """Returns the path of a repository url without the leading slash.

    If the result would be empty, the full URL is returned.
    """
    if not repo_url:
        return ""
    repo = urllib.parse.urlsplit(repo_url).path.strip().strip("/")
    return repo if repo else repo_url


def repo_branch_url(repo: Repo) -> str:
    """Generate a url for a given repo accounting for branches."""
    if not repo.is_git:
        return repo.url

    if "git.test" in repo.normalized_url:
        # For some local testing repos, there is a different URL pattern.
        template = "{repo.normalized_url}/log/?h={repo.default_branch}"
    else:
        template = "{repo.normalized_url}/tree/{repo.default_branch}"
    return template.format(repo=repo)


GRAPH_DRAWING_COL_WIDTH = 14
GRAPH_DRAWING_HEIGHT = 44
GRAPH_DRAWING_COLORS = [
    "#cc0000",
    "#cc0099",
    "#6600cc",
    "#0033cc",
    "#00cccc",
    "#00cc33",
    "#66cc00",
    "#cc9900",
]


def graph_width(cols: int) -> int:
    return GRAPH_DRAWING_COL_WIDTH * cols


def graph_height() -> int:
    return GRAPH_DRAWING_HEIGHT


def graph_x_pos(col: int) -> int:
    return (GRAPH_DRAWING_COL_WIDTH * col) + (GRAPH_DRAWING_COL_WIDTH // 2)


def graph_color(col: int) -> str:
    return GRAPH_DRAWING_COLORS[col % len(GRAPH_DRAWING_COLORS)]


def graph_above_path(col: int, above: int) -> str:
    commands = [
        "M {x} {y}".format(x=graph_x_pos(above), y=0),
        "C {x1} {y1}, {x2} {y2}, {x} {y}".format(
            x1=graph_x_pos(above),
            y1=GRAPH_DRAWING_HEIGHT / 4,
            x2=graph_x_pos(col),
            y2=GRAPH_DRAWING_HEIGHT / 4,
            x=graph_x_pos(col),
            y=GRAPH_DRAWING_HEIGHT / 2,
        ),
    ]
    return " ".join(commands)


def graph_below_path(col: int, below: int) -> str:
    commands = [
        "M {x} {y}".format(x=graph_x_pos(col), y=GRAPH_DRAWING_HEIGHT / 2),
        "C {x1} {y1}, {x2} {y2}, {x} {y}".format(
            x1=graph_x_pos(col),
            y1=3 * GRAPH_DRAWING_HEIGHT / 4,
            x2=graph_x_pos(below),
            y2=3 * GRAPH_DRAWING_HEIGHT / 4,
            x=graph_x_pos(below),
            y=GRAPH_DRAWING_HEIGHT,
        ),
    ]
    return " ".join(commands)


def message_type_to_notification_class(flash_message_category: str) -> str:
    """Map a Flask flash message category to a Bulma notification CSS class.

    See https://bulma.io/documentation/elements/notification/ for the list of
    Bulma notification states.
    """
    levels = messages.DEFAULT_LEVELS
    return {
        levels["INFO"]: "is-info",
        levels["SUCCESS"]: "is-success",
        levels["WARNING"]: "is-warning",
        levels["ERROR"]: "is-danger",
    }.get(flash_message_category, "is-info")


def environment(**options):  # noqa: ANN201
    env = Environment(extensions=[CompressorExtension], **options)
    env.globals.update(
        {
            "config": settings,
            "get_messages": messages.get_messages,
            "graph_height": graph_height,
            "treeherder_link": treeherder_link,
            "new_settings_form": UserSettingsForm,
            "static_url": settings.STATIC_URL,
            "url": reverse,
        }
    )
    env.filters.update(
        {
            "avatar_url": avatar_url,
            "bug_url": bug_url,
            "escape_html": escape_html,
            "graph_above_path": graph_above_path,
            "graph_below_path": graph_below_path,
            "graph_color": graph_color,
            "graph_width": graph_width,
            "graph_x_pos": graph_x_pos,
            "linkify_bug_numbers": linkify_bug_numbers,
            "linkify_faq": linkify_faq,
            "linkify_revision_ids": linkify_revision_ids,
            "linkify_revision_urls": linkify_revision_urls,
            "linkify_sec_bug_docs": linkify_sec_bug_docs,
            "linkify_transplant_details": linkify_transplant_details,
            "message_type_to_notification_class": message_type_to_notification_class,
            "repo_branch_url": repo_branch_url,
            "repo_path": repo_path,
            "reason_category_to_display": reason_category_to_display,
            "reviewer_to_action_text": reviewer_to_action_text,
            "reviewer_to_status_badge_class": reviewer_to_status_badge_class,
            "revision_status_to_badge_class": revision_status_to_badge_class,
            "revision_url": revision_url,
            "static": static,
            "tostatusbadgeclass": tostatusbadgeclass,
            "tostatusbadgename": tostatusbadgename,
            "uplift_status_icon_class": uplift_status_icon_class,
            "uplift_status_label": uplift_status_label,
            "uplift_status_tag_class": uplift_status_tag_class,
            "tree_category_to_display": tree_category_to_display,
            "treestatus_to_status_badge_class": treestatus_to_status_badge_class,
        }
    )
    return env
