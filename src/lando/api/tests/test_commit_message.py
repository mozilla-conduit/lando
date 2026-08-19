import pytest

from lando.api.legacy.commit_message import (
    bug_list_to_commit_string,
    format_commit_message,
    is_backout,
    parse_backouts,
    parse_bugs,
    split_title_and_summary,
)

COMMIT_MESSAGE = """
Bug 1 - A title. r=reviewer_one,reviewer.two

A summary.

Differential Revision: http://phabricator.test/D123
""".strip()

FIRST_LINE = COMMIT_MESSAGE.split("\n")[0]


def test_commit_message_for_multiple_reviewers():
    reviewers = ["reviewer_one", "reviewer.two"]
    commit_message = format_commit_message(
        "A title.", 1, reviewers, [], "A summary.", "http://phabricator.test/D123"
    )
    assert commit_message == (FIRST_LINE, COMMIT_MESSAGE)


def test_commit_message_blank_summary():
    first_line, message = format_commit_message(
        "A title.", 1, ["reviewer"], [], "", "http://phabricator.test/D123"
    )

    # A blank summary should result in only a single blank line between
    # the title and other fields, not several.
    assert len(message.splitlines()) == 3


@pytest.mark.parametrize(
    "reviewer_text",
    [
        "r?blocker! r?didnt_review",
        "r?blocker!,didnt_review",
        "r?blocker! r?didnt_review!",
        "r?blocker!,didnt_review!",
        "r?didnt_review r?blocker!",
        "r?didnt_review,blocker!",
        "r?didnt_review! r?blocker",
        "r?didnt_review!,blocker",
        "r=blocker! r=didnt_review",
        "r=blocker!,didnt_review",
        "r=blocker! r=didnt_review!",
        "r=blocker!,didnt_review!",
        "r=didnt_review r=blocker!",
        "r=didnt_review,blocker!",
        "r=didnt_review! r=blocker",
        "r=didnt_review!,blocker",
    ],
)
def test_commit_message_blocking_reviewers_requested(reviewer_text):
    commit_message = format_commit_message(
        "A title! {}".format(reviewer_text),
        1,
        ["blocker"],
        [],
        "",
        "http://phabricator.test/D123",
    )

    assert commit_message[0] == "Bug 1 - A title! r=blocker"


@pytest.mark.parametrize(
    "reviewer_text",
    [
        "r?bogus",
        "a=bogus",
        "a=bogus r?bogus",
        "a=bogus r=bogus",
        "r?bogus a=bogus",
        "r=bogus a=bogus",
        "r?#group1",
        "r?#group1, #group2",
        "r?reviewer_one,#group1",
        "r?#group1 r?reviewer.two",
        "r?#group1! r?group2",
        "r?#group1 r?group2!",
        "r?#group1! r?group2!",
        "r?#group1, reviewer.two!",
        "r=.a",
        "r=..a",
        "r=a...a",
        "r=a.b",
        "r=a.b.c",
        "r=aa,.a,..a,a...a,a.b,a.b.c",
    ],
)
def test_commit_message_reviewers_replaced(reviewer_text):
    reviewers = ["reviewer_one", "reviewer.two"]
    commit_message = format_commit_message(
        "A title. {}".format(reviewer_text),
        1,
        reviewers,
        [],
        "A summary.",
        "http://phabricator.test/D123",
    )
    assert commit_message == (FIRST_LINE, COMMIT_MESSAGE)


def test_commit_message_with_flags():
    reviewers = ["reviewer_one", "reviewer.two"]
    commit_message = format_commit_message(
        title="A title.",
        bug=1,
        reviewers=reviewers,
        approvals=[],
        summary="A summary.",
        revision_url="http://phabricator.test/D123",
        flags=["DONTBUILD"],
    )
    assert commit_message[0] == FIRST_LINE + " DONTBUILD"


def test_commit_message_with_flags_does_not_duplicate_flags():
    reviewers = ["reviewer_one", "reviewer.two"]
    commit_message = format_commit_message(
        title="A title. DONTBUILD",
        bug=1,
        reviewers=reviewers,
        approvals=[],
        summary="A summary.",
        revision_url="http://phabricator.test/D123",
        flags=["DONTBUILD"],
    )
    assert commit_message[0].count("DONTBUILD") == 1


@pytest.mark.xfail(strict=True)
def test_group_reviewers_replaced_with_period_at_end():
    """Test unexpected period after reviewer name."""
    # NOTE: the parser stops parsing after the period at the end of a reviewer
    # name, therefore any other reviewers past the first period will not be
    # parsed correctly, and the output will be mangled. This should be fixed
    # and the test should be updated.

    reviewers = ["reviewer_one", "reviewer.two"]
    commit_message = format_commit_message(
        "A title. r=a.,b",
        1,
        reviewers,
        [],
        "A summary.",
        "http://phabricator.test/D123",
    )

    # This is the current behaviour
    assert commit_message == (
        "Bug 1 - A title. r=reviewer_one,reviewer.two.,b",
        "Bug 1 - A title. r=reviewer_one,reviewer.two.,b\n\n"
        "A summary.\n\nDifferential Revision: http://phabricator.test/D123",
    )

    # This is the desired future behaviour
    assert commit_message == (
        "Bug 1 - A title. r=reviewer_one,reviewer.two.",
        "Bug 1 - A title. r=reviewer_one,reviewer.two.\n\n"
        "A summary.\n\nDifferential Revision: http://phabricator.test/D123",
    )


@pytest.mark.parametrize(
    "message, title, summary",
    [
        ("title only", "title only", ""),
        ("title only\n\n", "title only", ""),
        ("title\n\nand summary", "title", "and summary"),
        ("title\n\nmultiline\n\nsummary", "title", "multiline\n\nsummary"),
    ],
)
def test_split_title_and_summary(message, title, summary):
    parsed_title, parsed_summary = split_title_and_summary(message)
    assert parsed_title == title
    assert parsed_summary == summary


def test_relman_reviews_become_approvals():
    commit_message = format_commit_message(
        "A title r?#release-managers!",
        1,
        [],
        ["ryanvm"],
        ("A summary.\n\nOriginal Revision: http://phabricator.test/D1"),
        "http://phabricator.test/D123",
    )

    assert commit_message == (
        "Bug 1 - A title  a=ryanvm",
        "Bug 1 - A title  a=ryanvm\n\n"
        "A summary.\n\n"
        "Original Revision: http://phabricator.test/D1\n\n"
        "Differential Revision: http://phabricator.test/D123",
    )


def test_bug_list_to_commit_string():
    assert bug_list_to_commit_string([]) == "No bug", (
        "Empty input should return `No bug`"
    )
    assert bug_list_to_commit_string(["123"]) == "Bug 123", (
        "Single bug should return with `bug` and number."
    )
    assert bug_list_to_commit_string(["123", "456"]) == "Bug 123, 456", (
        "Multiple bugs should return comma separated list."
    )
    assert bug_list_to_commit_string(["123", "123"]) == "Bug 123", (
        "Multiple bugs should be deduplicated."
    )


BUG_COMMIT_MESSAGE = """
Bug 1803416 - Part 1: WindowsAppSDK toolchain. r?glandium

This follows an approach suggested
[here](https://github.com/microsoft/WindowsAppSDK/discussions/1891#discussioncomment-2043601).

Differential Revision: https://phabricator.services.mozilla.com/D223371
""".lstrip()


def test_parse_bugs():
    assert parse_bugs(BUG_COMMIT_MESSAGE) == [1803416], (
        "`parse_bugs` should only return the appropriate bug numbers."
    )


HG_STYLE_BACKOUT = """\
Backed out 5 changesets (bug 1965330) for reftest failures

Backed out changeset 586f132b2ad7 (bug 1965330)
Backed out changeset 6cd2e3e3e11c (bug 1965330)
Backed out changeset 57b4521b3f44 (bug 1965330)
Backed out changeset f758a758914e (bug 1965330)
Backed out changeset cd6ed268f238 (bug 1965330)

Differential Revision: https://phabricator.services.mozilla.com/D252667
"""

# Note that the last `This reverts commit ...` line is missing a trailing `.`. This is
# to account for potential manual editing of revert messages containing all the needed
# information but not strictly adhering to the automatic format from Git.
GIT_STYLE_REVERT = """\
Revert "Bug 2030542, Bug 2062193, Bug 2062191, Bug 2062186, Bug 2062189 - Wait for the favicon to reach the top sites list in browser_ext_topSites.js, and re-enable the test on linux x11 opt, r=extension-reviewers,rpl." for causing bc failures @browser_ext_url_overrides_newtab.js.

This reverts commit ba2c3a5b0735e67b4fd904a6fd324a9f79c44cf1.

Revert "Bug 2062193 - Expect windows.update() to clamp an off-screen position to the screen's available area in browser_ext_windows_size.js, and re-enable the test on mac, r=extension-reviewers,rpl."

This reverts commit 36ffcad0ba0cb10d8348d99fbe0095359e03fcf4.

Revert "Bug 2062191 - Use fake media streams in browser_ext_webrtc.js and re-enable it on mac, r=extension-reviewers,rpl."

This reverts commit f22844d2d7c424875ac74b56d88590f8d489e9f6.

Revert "Bug 2062186 - Fix the intermittent stale about:preferences tab in browser_ext_url_overrides_newtab.js, r=extension-reviewers,rpl."

This reverts commit c02ebe1d487482c3ddfdffde9be1c46be1ce4f6d.

Revert "Bug 2062189 - Wait for the parent process to register the menu item before opening a context menu in the browserAction, pageAction and sidebarAction contextMenu tests, r=extension-reviewers,rpl."

This reverts commit e3f81fcb94c16422e2643009af485d88647fdfd8
"""


@pytest.mark.parametrize(
    "commit_message,expected_parsed",
    (
        ("Backed out changeset 4910f543acd8", (["4910f543acd8"], [])),
        ("Backout of ceac31c0ce89 due to bustage", (["ceac31c0ce89"], [])),
        (
            "Revert to changeset 41f80b316d60 due to incomplete backout",
            (["41f80b316d60"], []),
        ),
        (
            "Backout changesets  9e4ab3907b29, 3abc0dbbf710 due to m-oth permaorange",
            (["9e4ab3907b29", "3abc0dbbf710"], []),
        ),
        (
            HG_STYLE_BACKOUT,
            (
                [
                    "586f132b2ad7",
                    "6cd2e3e3e11c",
                    "57b4521b3f44",
                    "f758a758914e",
                    "cd6ed268f238",
                ],
                [1965330],
            ),
        ),
        (
            GIT_STYLE_REVERT,
            (
                [
                    "ba2c3a5b0735e67b4fd904a6fd324a9f79c44cf1",
                    "36ffcad0ba0cb10d8348d99fbe0095359e03fcf4",
                    "f22844d2d7c424875ac74b56d88590f8d489e9f6",
                    "c02ebe1d487482c3ddfdffde9be1c46be1ce4f6d",
                    "e3f81fcb94c16422e2643009af485d88647fdfd8",
                ],
                [2030542, 2062193, 2062191, 2062186, 2062189],
            ),
        ),
    ),
)
def test_backouts_parsing(
    commit_message: str, expected_parsed: tuple[list[str], list[str]]
):
    assert is_backout(commit_message), "Backout message not recognised as such"

    parsed = parse_backouts(commit_message)
    assert parsed == expected_parsed, "Backout message incorrectly parsed"
