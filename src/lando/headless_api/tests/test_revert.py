import json
from unittest import mock

import pytest
from django.contrib.auth.models import Permission
from pydantic import ValidationError

from lando.headless_api.api import resolve_action
from lando.headless_api.models.automation_job import AutomationAction, AutomationJob
from lando.main.models import JobStatus, Repo
from lando.main.models.configuration import (
    ConfigurationKey,
    ConfigurationVariable,
    VariableTypeChoices,
)
from lando.main.models.profile import SCM_ALLOW_DIRECT_PUSH
from lando.main.scm import SCMType


def revert_action(**kwargs):
    return {
        "action": "revert",
        "commit": "a" * 40,
        **kwargs,
    }


@pytest.mark.parametrize(
    "data",
    [
        {"commit": "HEAD"},
        {"commit": "a" * 39},
        {"commit": "a" * 40 + "\n"},
        {"commit": "--help"},
        {"commit": "a" * 40 + "..HEAD"},
    ],
)
def test_revert_validation(data):
    with pytest.raises(ValidationError):
        resolve_action(revert_action(**data))


def post_revert(
    client,
    headless_user,
    operation,
    repo_name,
    can_revert=True,
    allowed_repos=("firefox-autoland",),
    enabled=True,
    automation=False,
):
    user, token = headless_user
    if not automation:
        user.user_permissions.clear()
    if can_revert:
        user.user_permissions.add(Permission.objects.get(codename="can_revert_commits"))
    if allowed_repos is not None:
        ConfigurationVariable.set(
            ConfigurationKey.REVERT_ALLOWED_REPOS,
            VariableTypeChoices.JSON,
            json.dumps(list(allowed_repos)),
        )
    Repo.objects.create(
        name=repo_name,
        scm_type=SCMType.GIT,
        automation_enabled=enabled,
        required_automation_permission=SCM_ALLOW_DIRECT_PUSH,
    )
    return client.post(
        f"/api/repo/{repo_name}",
        data=operation,
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    ), token


@pytest.mark.django_db
@pytest.mark.parametrize(
    "repo_name,can_revert,allowed_repos,enabled,expected",
    [
        ("firefox-autoland", True, ("firefox-autoland",), True, 202),
        ("firefox-autoland", True, ("ff-test-dev", "firefox-autoland"), True, 202),
        ("firefox-main", True, ("firefox-autoland",), True, 403),
        ("firefox-autoland", False, ("firefox-autoland",), True, 403),
        ("firefox-autoland", True, None, True, 403),
        ("firefox-autoland", True, (), True, 403),
        ("firefox-autoland", True, ("firefox-autoland",), False, 400),
    ],
)
def test_revert_authorization(
    client, headless_user, repo_name, can_revert, allowed_repos, enabled, expected
):
    response, token = post_revert(
        client,
        headless_user,
        {"actions": [revert_action(), revert_action(commit="b" * 40)]},
        repo_name,
        can_revert,
        allowed_repos,
        enabled,
    )
    assert response.status_code == expected, response.content
    assert AutomationJob.objects.count() == (expected == 202)
    if expected == 202:
        job = AutomationJob.objects.get()
        assert [action.data for action in job.actions.order_by("order")] == [
            revert_action(),
            revert_action(commit="b" * 40),
        ]
        assert (
            client.get(
                f"/api/job/{job.id}", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 200
        )


@pytest.mark.django_db
def test_revert_automation_permission_is_not_enough(client, headless_user):
    response, _token = post_revert(
        client,
        headless_user,
        {"actions": [revert_action()]},
        "firefox-autoland",
        can_revert=False,
        automation=True,
    )
    assert response.status_code == 403, response.content


@pytest.mark.django_db
@pytest.mark.parametrize(
    "operation",
    [
        {"actions": [revert_action(), {"action": "tag", "name": "bad"}]},
        {"actions": [{"action": "tag", "name": "bad"}, revert_action()]},
        {"actions": [revert_action()], "relbranch": {"branch_name": "other"}},
    ],
)
def test_revert_rejects_other_operations(client, headless_user, operation):
    response, _token = post_revert(client, headless_user, operation, "firefox-autoland")
    assert response.status_code == 403, response.content
    assert not AutomationJob.objects.exists()


@pytest.mark.django_db
def test_revert_never_skips_checks():
    from lando.api.legacy.workers.automation_worker import AutomationWorker

    job = AutomationJob.objects.create(status=JobStatus.SUBMITTED)
    AutomationAction.objects.create(
        job_id=job,
        action_type="revert",
        data=revert_action(),
        order=0,
    )
    assert not AutomationWorker.skip_checks(None, job, [mock.Mock(desc="a=release")])
