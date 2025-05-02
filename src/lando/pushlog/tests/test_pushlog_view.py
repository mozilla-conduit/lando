from io import StringIO
from typing import Callable

import pytest
from django.core.management import call_command


@pytest.mark.parametrize(
    "with_commits,with_tags",
    [
        (None, None),
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ],
)
@pytest.mark.django_db
def test_pushlog_view(
    make_commit: Callable,
    make_push: Callable,
    make_repo: Callable,
    make_tag: Callable,
    with_commits: bool | None,
    with_tags: bool | None,
) -> None:
    repo = make_repo(1)
    commit = make_commit(repo, 1)
    tag = make_tag(repo, 1, commit)
    push = make_push(repo, [commit], [tag])
    push.notified = True
    push.save()

    out = StringIO()
    opts = {
        "repo": repo.name,
    }

    if with_commits is not None:
        opts["with_commits"] = with_commits
    if with_tags is not None:
        opts["with_tags"] = with_tags

    call_command("pushlog_view", stdout=out, **opts)

    output = out.getvalue()

    if with_commits is False:
        assert str(commit) not in output, "Commit unexpectedly present in output"
    else:
        # If unset, defaults to True.
        assert str(commit) in output, "Commit not present in output"

    if with_tags is False:
        assert str(tag) not in output, "Tag unexpectedly present in output"
    else:
        # If unset, defaults to True.
        assert str(tag) in output, "Tag not present in output"
