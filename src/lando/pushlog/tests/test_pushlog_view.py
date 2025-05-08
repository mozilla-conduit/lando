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


@pytest.mark.django_db
def test_pushlog_view_filtering(
    make_commit: Callable,
    make_push: Callable,
    make_repo: Callable,
    make_tag: Callable,
) -> None:
    repo = make_repo(1)
    commit = make_commit(repo, 1)
    push1 = make_push(repo, [commit], [])
    push1.notified = True
    push1.save()

    tag = make_tag(repo, 1, commit)
    push2 = make_push(repo, [], [tag])
    push2.notified = True
    push2.save()

    out = StringIO()
    opts = {
        "repo": repo.name,
        "push_id": 1,
    }

    call_command("pushlog_view", stdout=out, **opts)
    output = out.getvalue()

    assert str(commit) in output
    assert str(tag) not in output, "Other Pushes than selected found in output."

    out = StringIO()
    commits_opts = {
        "repo": repo.name,
        "commits_only": True,
    }
    call_command("pushlog_view", stdout=out, **commits_opts)
    output = out.getvalue()

    assert str(push1) in output
    assert str(push2) not in output, "Tags push found in --tags-only output"
    assert str(commit) in output
    assert str(tag) not in output, "Tags found in --commits-only output"

    out = StringIO()
    tags_opts = {
        "repo": repo.name,
        "tags_only": True,
    }
    call_command("pushlog_view", stdout=out, **tags_opts)
    output = out.getvalue()

    assert str(push1) not in output, "Commit push found in --tags-only output"
    assert str(push2) in output
    assert str(commit) not in output, "Commits found in --tags-only output"
    assert str(tag) in output
