from dataclasses import replace

import pytest


@pytest.mark.parametrize(
    "desc,expected_bug_ids",
    (
        ("Bug 123456: uplift a fix r=reviewer", ["123456"]),
        ("No bug: uplift a fix\n\nRelated to bug 999999.", []),
    ),
)
def test_commit_data_bug_ids(make_scm_commit, desc: str, expected_bug_ids: list[str]):
    """Only the first line of the commit message should be scanned for bugs."""
    commit = make_scm_commit(1, desc=desc)

    assert commit.bug_ids == expected_bug_ids, (
        "`bug_ids` should only return bugs referenced in the commit title."
    )


def test_commit_data_bug_ids_empty_desc(make_scm_commit):
    """A commit with an empty message should reference no bugs."""
    commit = replace(make_scm_commit(1), desc="")

    assert commit.bug_ids == [], (
        "`bug_ids` should be empty for a commit with no message."
    )
