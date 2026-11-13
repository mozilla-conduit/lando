import logging
import time
from typing import (
    Any,
)

import requests
from packaging.version import (
    InvalidVersion,
    Version,
)

from lando.api.legacy import bmo
from lando.main.models.configuration import ConfigurationKey, ConfigurationVariable

logger = logging.getLogger(__name__)

UPLIFT_BUG_UPDATE_RETRIES = 3

# The longest resolution diff posted to Phabricator, so a sprawling resolution
# can't produce unreadable details.
MAX_RESOLUTION_DIFF_LENGTH = 100_000


def parse_milestone_version(milestone_contents: str) -> Version:
    """Parse the milestone version from the contents of `config/milestone.txt`."""
    try:
        # Get the last line of the file.
        milestone = milestone_contents.strip().splitlines()[-1]

        return Version(milestone)
    except InvalidVersion as e:
        raise ValueError(
            f"`config/milestone.txt` is not in the expected format:\n{milestone_contents}"
        ) from e


def create_uplift_bug_update_payload(
    bug: dict, repo_name: str, milestone: int, milestone_tracking_flag_template: str
) -> dict[str, Any]:
    """Create a payload for updating a bug using the BMO REST API.

    Examines the data returned from the BMO REST API bug access endpoint to
    determine if any post-uplift updates should be made to the bug.

    - Sets the `status_firefoxXX` flags to `fixed`.
    - Removes `[checkin-needed-*]` from the bug whiteboard.

    Returns the bug update payload to be passed to the BMO REST API.
    """
    payload: dict[str, Any] = {
        "ids": [int(bug["id"])],
    }

    milestone_tracking_flag = milestone_tracking_flag_template.format(
        milestone=milestone
    )
    if (
        milestone_tracking_flag
        and "keywords" in bug
        and "leave-open" not in bug["keywords"]
        and milestone_tracking_flag in bug
    ):
        # Set the status of a bug to fixed if the fix was uplifted to a branch
        # and the "leave-open" keyword is not set.
        payload[milestone_tracking_flag] = "fixed"

    checkin_needed_flag = f"[checkin-needed-{repo_name}]"
    if "whiteboard" in bug and checkin_needed_flag in bug["whiteboard"]:
        # Remove "[checkin-needed-beta]" etc. texts from the whiteboard.
        payload["whiteboard"] = bug["whiteboard"].replace(checkin_needed_flag, "")

    return payload


def update_bugs_for_uplift(
    repo_name: str,
    milestone_file_contents: str,
    milestone_tracking_flag_template: str,
    bug_ids: list[str],
):
    """Update Bugzilla bugs for uplift."""
    params = {
        "id": ",".join(bug_ids),
    }

    # Get information about the parsed bugs.
    bugs = bmo.uplift_get_bug(params)["bugs"]

    # Get the major release number from `config/milestone.txt`.
    milestone = parse_milestone_version(milestone_file_contents)

    # Create bug update payloads.
    payloads = [
        create_uplift_bug_update_payload(
            bug, repo_name, milestone.major, milestone_tracking_flag_template
        )
        for bug in bugs
    ]

    for payload in payloads:
        for i in range(1, UPLIFT_BUG_UPDATE_RETRIES + 1):
            # Update bug and account for potential errors.
            try:
                bmo.uplift_update_bug(payload)

                break
            except requests.RequestException as e:
                if i == UPLIFT_BUG_UPDATE_RETRIES:
                    raise e

                logger.exception(
                    f"Error while updating bugs after uplift on attempt {i}, retrying...\n"
                    f"{str(e)}"
                )

                time.sleep(1.0 * i)


def is_uplift_resolution_enabled() -> bool:
    """Return `True` when uplift merge conflicts may be handed to Hackbot.

    Off unless the `UPLIFT_HACKBOT_ENABLED` configuration variable is set, so the
    whole workflow can be switched off without a deploy.
    """
    return ConfigurationVariable.get(ConfigurationKey.UPLIFT_HACKBOT_ENABLED, False)


def format_resolution_details(
    revision_id: int, train: str, resolution_diff: str
) -> str:
    """Return the Remarkup details of a merge conflict's AI change approval request.

    `resolution_diff` shows the conflicted files, conflict markers included,
    changing into Hackbot's resolution, so a reviewer can check each choice it made.
    """
    lines = [
        f"Hackbot resolved a merge conflict when Lando uplifted D{revision_id} "
        f"to `{train}`.",
    ]

    if not resolution_diff:
        lines += [
            "",
            "Lando could not rebuild the conflicted files to show how Hackbot "
            "resolved them.",
        ]
        return "\n".join(lines)

    truncated = len(resolution_diff) > MAX_RESOLUTION_DIFF_LENGTH
    lines += [
        "",
        "How Hackbot changed the conflicted files, conflict markers included:",
        "",
        "```lang=diff, lines=40",
        resolution_diff[:MAX_RESOLUTION_DIFF_LENGTH].rstrip("\n"),
        "```",
    ]
    if truncated:
        lines += ["", "The diff was too long to show in full, so it was truncated."]
    return "\n".join(lines)


def format_later_revision_details(revision_id: int, train: str) -> str:
    """Return the Remarkup details of an approval request after the conflicting revision.

    Hackbot resolves the whole stack at once, so a revision after the conflicting
    one may hold its changes too, but Lando has no conflicted tree to compare it with.
    """
    return (
        f"Hackbot resolved a merge conflict when Lando uplifted D{revision_id} "
        f"to `{train}`, and may have changed this later revision of the stack too. "
        "Compare it with the revision it uplifts."
    )
