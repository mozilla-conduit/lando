from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from lando.api.legacy.transplants import (
    RevisionWarning,
    StackAssessment,
    blocker_author_planned_changes,
    blocker_prevent_symlinks,
    blocker_revision_data_classification,
    blocker_try_task_config,
    blocker_uplift_approval,
    warning_multiple_authors,
    warning_not_accepted,
    warning_previously_landed,
    warning_reviews_not_current,
    warning_revision_secure,
    warning_wip_commit_message,
)
from lando.main.models import DONTBUILD, SCM_CONDUIT, Repo
from lando.main.models.landing_job import (
    LandingJob,
    LandingJobStatus,
    add_job_with_revisions,
)
from lando.main.models.revision import Revision
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG
from lando.utils.phabricator import PhabricatorRevisionStatus, ReviewerStatus
from lando.utils.tasks import admin_remove_phab_project


def _create_landing_job(
    *,
    landing_path=((1, 1),),  # noqa: ANN001
    revisions=None,  # noqa: ANN001
    requester_email="tuser@example.com",  # noqa: ANN001
    repository_name="mozilla-central",  # noqa: ANN001
    repository_url="http://hg.test",  # noqa: ANN001
    status=None,  # noqa: ANN001
):
    job_params = {
        "requester_email": requester_email,
        "repository_name": repository_name,
        "repository_url": repository_url,
        "status": status,
    }
    revisions = []
    for revision_id, diff_id in landing_path:
        revision = Revision.one_or_none(revision_id=revision_id)
        if not revision:
            revision = Revision(revision_id=revision_id)
        revision.diff_id = diff_id
        revisions.append(revision)
    for revision in revisions:
        revision.save()
    job = add_job_with_revisions(revisions, **job_params)
    return job


def _create_landing_job_with_no_linked_revisions(
    *,
    landing_path=((1, 1),),  # noqa: ANN001
    revisions=None,  # noqa: ANN001
    requester_email="tuser@example.com",  # noqa: ANN001
    repository_name="mozilla-central",  # noqa: ANN001
    repository_url="http://hg.test",  # noqa: ANN001
    status=None,  # noqa: ANN001
):
    # Create a landing job without a direct link to revisions, but by referencing
    # revisions in revision_to_diff_id and revision_order
    job_params = {
        "requester_email": requester_email,
        "repository_name": repository_name,
        "repository_url": repository_url,
        "status": status,
    }
    job = LandingJob(**job_params)
    job.save()
    revisions = []
    for revision_id, diff_id in landing_path:
        revision = Revision.one_or_none(revision_id=revision_id)
        if not revision:
            revision = Revision(revision_id=revision_id)
        revision.diff_id = diff_id
        revisions.append(revision)
    for revision in revisions:
        revision.save()
    job.revision_to_diff_id = {
        str(revision.revision_id): revision.diff_id for revision in revisions
    }
    job.revision_order = [str(revision.revision_id) for revision in revisions]
    job.save()
    return job


@pytest.mark.django_db(transaction=True)
def test_dryrun_no_warnings_or_blockers(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))
    phabdouble.reviewer(r1, phabdouble.project("reviewer2"))

    response = proxy_client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        permissions=mock_permissions,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    expected_json = {"confirmation_token": None, "warnings": [], "blocker": None}
    assert response.json == expected_json


@pytest.mark.django_db(transaction=True)
def test_dryrun_invalid_path_blocks(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
):
    d1 = phabdouble.diff()
    d2 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    r2 = phabdouble.revision(
        diff=d2, repo=phabdouble.repo(name="not-mozilla-central"), depends_on=[r1]
    )
    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))
    phabdouble.reviewer(r1, phabdouble.project("reviewer2"))

    response = proxy_client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
            ]
        },
        permissions=mock_permissions,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    assert (
        "Depends on D1 which is open and has a different repository"
        in response.json["blocker"]
    )


@pytest.mark.django_db
def test_dryrun_published_parent(
    proxy_client,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
):
    d1 = phabdouble.diff()
    d2 = phabdouble.diff()

    repo = phabdouble.repo()

    reviewer = phabdouble.user(username="reviewer")

    r1 = phabdouble.revision(
        diff=d1, repo=repo, status=PhabricatorRevisionStatus.PUBLISHED
    )
    r2 = phabdouble.revision(diff=d2, repo=repo, depends_on=[r1])

    phabdouble.reviewer(r1, reviewer)
    phabdouble.reviewer(r2, reviewer)

    response = proxy_client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
            ]
        },
        permissions=mock_permissions,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    assert response.json["blocker"] is None


@pytest.mark.django_db
def test_dryrun_open_parent(
    proxy_client,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    d1 = phabdouble.diff()
    d2 = phabdouble.diff()

    repo = phabdouble.repo()

    reviewer = phabdouble.user(username="reviewer")

    r1 = phabdouble.revision(
        diff=d1, repo=repo, status=PhabricatorRevisionStatus.ACCEPTED
    )
    r2 = phabdouble.revision(diff=d2, repo=repo, depends_on=[r1])

    phabdouble.reviewer(r1, reviewer)
    phabdouble.reviewer(r2, reviewer)

    response = proxy_client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                # Set the landing path to try and land only r2, despite r1 being open
                # and part of the stack.
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
            ]
        },
        permissions=mock_permissions,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    assert (
        "The requested set of revisions are not landable." in response.json["blocker"]
    ), "Landing should be blocked due to r1 still being open and part of the stack."


@pytest.mark.django_db(transaction=True)
def test_dryrun_in_progress_transplant_blocks(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    repo = phabdouble.repo()

    # Structure:
    # *     merge
    # |\
    # | *   r2
    # *     r1
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=repo)

    # merge
    phabdouble.revision(diff=phabdouble.diff(), repo=repo, depends_on=[r1, r2])

    # Create am in progress transplant on r2, which should
    # block attempts to land r1.
    _create_landing_job(
        landing_path=[(r1["id"], d1["id"])],
        status=LandingJobStatus.SUBMITTED,
    )

    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))
    phabdouble.reviewer(r1, phabdouble.project("reviewer2"))

    response = proxy_client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        permissions=mock_permissions,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    assert response.json["blocker"] == (
        "A landing for revisions in this stack is already in progress."
    )


@pytest.mark.django_db(transaction=True)
def test_dryrun_reviewers_warns(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(
        r1, phabdouble.user(username="reviewer"), status=ReviewerStatus.REJECTED
    )

    response = proxy_client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        permissions=mock_permissions,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    assert response.json["warnings"]
    assert response.json["warnings"][0]["id"] == 0
    assert response.json["confirmation_token"] is not None


@pytest.mark.django_db(transaction=True)
def test_dryrun_codefreeze_warn(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    codefreeze_datetime,  # noqa: ANN001
    monkeypatch,  # noqa: ANN001
    request_mocker,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    product_details = "https://product-details.mozilla.org/1.0/firefox_versions.json"
    request_mocker.register_uri(
        "GET",
        product_details,
        json={
            "NEXT_SOFTFREEZE_DATE": "two_days_ago",
            "NEXT_MERGE_DATE": "tomorrow",
        },
    )
    monkeypatch.setattr("lando.api.legacy.transplants.datetime", codefreeze_datetime())
    mc_repo = Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-conduit",
        url="https://hg.test/mozilla-conduit",
        required_permission=SCM_CONDUIT,
        commit_flags=[DONTBUILD],
        product_details_url=product_details,
    )
    mc_mock = MagicMock()
    mc_mock.return_value = {"mozilla-central": mc_repo}
    monkeypatch.setattr("lando.main.models.Repo.get_mapping", mc_mock)

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(
        r1, phabdouble.user(username="reviewer"), status=ReviewerStatus.ACCEPTED
    )

    response = proxy_client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        permissions=mock_permissions,
    )

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.json[
        "warnings"
    ], "warnings should not be empty for a repo under code freeze"
    assert (
        response.json["warnings"][0]["id"] == 8
    ), "the warning ID should match the ID for warning_code_freeze"
    assert response.json["confirmation_token"] is not None


@pytest.mark.django_db(transaction=True)
def test_dryrun_outside_codefreeze(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    codefreeze_datetime,  # noqa: ANN001
    monkeypatch,  # noqa: ANN001
    request_mocker,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    product_details = "https://product-details.mozilla.org/1.0/firefox_versions.json"
    request_mocker.register_uri(
        "GET",
        product_details,
        json={
            "NEXT_SOFTFREEZE_DATE": "four_weeks_from_today",
            "NEXT_MERGE_DATE": "five_weeks_from_today",
        },
    )
    monkeypatch.setattr("lando.api.legacy.transplants.datetime", codefreeze_datetime())
    mc_repo = Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-conduit",
        url="https://hg.test/mozilla-conduit",
        required_permission=SCM_CONDUIT,
        commit_flags=[DONTBUILD],
        product_details_url=product_details,
    )
    mc_mock = MagicMock()
    mc_mock.return_value = {"mozilla-central": mc_repo}
    monkeypatch.setattr("lando.main.models.Repo.get_mapping", mc_mock)

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(
        r1, phabdouble.user(username="reviewer"), status=ReviewerStatus.ACCEPTED
    )

    response = proxy_client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        permissions=mock_permissions,
    )

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert not response.json["warnings"]


# auth related issue, blockers empty.
@pytest.mark.xfail
@pytest.mark.parametrize(
    "permissions,status,blocker",
    [
        (
            (),  # No permissions
            200,
            "You have insufficient permissions to land or your access has expired. "
            "main.scm_level_3 is required. See the FAQ for help.",
        ),
    ],
)
@pytest.mark.django_db(transaction=True)
def test_integrated_dryrun_blocks_for_bad_userinfo(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    permissions,  # noqa: ANN001
    status,  # noqa: ANN001
    blocker,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())

    response = proxy_client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        permissions=permissions,
        content_type="application/json",
    )

    assert response.status_code == status
    assert blocker in response.json["blocker"]


@pytest.mark.django_db(transaction=True)
def test_get_transplants_for_entire_stack(proxy_client, phabdouble):  # noqa: ANN001
    d1a = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1a, repo=phabdouble.repo())
    d1b = phabdouble.diff(revision=r1)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabdouble.repo(), depends_on=[r1])

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabdouble.repo(), depends_on=[r1])

    d_not_in_stack = phabdouble.diff()
    r_not_in_stack = phabdouble.revision(diff=d_not_in_stack, repo=phabdouble.repo())

    t1 = _create_landing_job(
        landing_path=[(r1["id"], d1a["id"])],
        status=LandingJobStatus.FAILED,
    )
    t2 = _create_landing_job(
        landing_path=[(r1["id"], d1b["id"])],
        status=LandingJobStatus.LANDED,
    )
    t3 = _create_landing_job(
        landing_path=[(r2["id"], d2["id"])],
        status=LandingJobStatus.SUBMITTED,
    )
    t4 = _create_landing_job(
        landing_path=[(r3["id"], d3["id"])],
        status=LandingJobStatus.LANDED,
    )

    t_not_in_stack = _create_landing_job(
        landing_path=[(r_not_in_stack["id"], d_not_in_stack["id"])],
        status=LandingJobStatus.LANDED,
    )

    response = proxy_client.get("/transplants?stack_revision_id=D{}".format(r2["id"]))
    assert len(response) == 4

    tmap = {i["id"]: i for i in response}
    assert t_not_in_stack.id not in tmap
    assert all(t.id in tmap for t in (t1, t2, t3, t4))


@pytest.mark.django_db(transaction=True)
def test_get_transplant_from_middle_revision(proxy_client, phabdouble):  # noqa: ANN001
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabdouble.repo(), depends_on=[r1])

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabdouble.repo(), depends_on=[r1])

    t = _create_landing_job(
        landing_path=[(r1["id"], d1["id"]), (r2["id"], d2["id"]), (r3["id"], d3["id"])],
        status=LandingJobStatus.FAILED,
    )

    response = proxy_client.get("/transplants?stack_revision_id=D{}".format(r2["id"]))
    assert len(response) == 1
    assert response[0]["id"] == t.id


@pytest.mark.django_db(transaction=True)
def test_get_transplant_not_authorized_to_view_revision(
    proxy_client, phabdouble  # noqa: ANN001
):
    # Create a transplant pointing at a revision that will not
    # be returned by phabricator.
    _create_landing_job(landing_path=[(1, 1)], status=LandingJobStatus.SUBMITTED)
    response = proxy_client.get("/transplants?stack_revision_id=D1")
    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_warning_previously_landed_no_landings(
    phabdouble, create_state  # noqa: ANN001
):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)
    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    diff = phabdouble.api_object_for(d, attachments={"commits": True})
    stack_state = create_state(revision)
    assert warning_previously_landed(revision, diff, stack_state) is None


@pytest.mark.parametrize(
    "create_landing_job",
    (_create_landing_job, _create_landing_job_with_no_linked_revisions),
)
@pytest.mark.django_db(transaction=True)
def test_warning_previously_landed_failed_landing(
    phabdouble, create_landing_job, create_state  # noqa: ANN001
):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)

    create_landing_job(
        landing_path=[(r["id"], d["id"])],
        status=LandingJobStatus.FAILED,
    )

    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    stack_state = create_state(revision)

    assert warning_previously_landed(revision, diff, stack_state) is None


@pytest.mark.parametrize(
    "create_landing_job",
    (_create_landing_job, _create_landing_job_with_no_linked_revisions),
)
@pytest.mark.django_db(transaction=True)
def test_warning_previously_landed_landed_landing(
    phabdouble, create_landing_job, create_state  # noqa: ANN001
):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)

    create_landing_job(
        landing_path=[(r["id"], d["id"])],
        status=LandingJobStatus.LANDED,
    )

    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    stack_state = create_state(revision)

    assert warning_previously_landed(revision, diff, stack_state) is not None


@pytest.mark.django_db
def test_warning_revision_secure_project_none(phabdouble, create_state):  # noqa: ANN001
    revision = phabdouble.api_object_for(
        phabdouble.revision(),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(revision)

    assert warning_revision_secure(revision, {}, stack_state) is None


@pytest.mark.django_db
def test_warning_revision_secure_is_secure(
    phabdouble, secure_project, create_state  # noqa: ANN001
):
    revision = phabdouble.api_object_for(
        phabdouble.revision(projects=[secure_project]),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(revision)

    assert warning_revision_secure(revision, {}, stack_state) is not None


@pytest.mark.django_db
def test_warning_revision_secure_is_not_secure(
    phabdouble, secure_project, create_state  # noqa: ANN001
):
    not_secure_project = phabdouble.project("not_secure_project")
    revision = phabdouble.api_object_for(
        phabdouble.revision(projects=[not_secure_project]),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(revision)

    assert warning_revision_secure(revision, {}, stack_state) is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [
        s
        for s in PhabricatorRevisionStatus
        if s is not PhabricatorRevisionStatus.ACCEPTED
    ],
)
def test_warning_not_accepted_warns_on_other_status(
    phabdouble, status, create_state  # noqa: ANN001
):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=status),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(revision)

    assert warning_not_accepted(revision, {}, stack_state) is not None


@pytest.mark.django_db
def test_warning_not_accepted_no_warning_when_accepted(
    phabdouble, create_state  # noqa: ANN001
):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=PhabricatorRevisionStatus.ACCEPTED),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(revision)

    assert warning_not_accepted(revision, {}, stack_state) is None


@pytest.mark.django_db
def test_warning_reviews_not_current_warns_on_unreviewed_diff(
    phabdouble, create_state  # noqa: ANN001
):
    d_reviewed = phabdouble.diff()
    r = phabdouble.revision(diff=d_reviewed)
    phabdouble.reviewer(
        r,
        phabdouble.user(username="reviewer"),
        on_diff=d_reviewed,
        status=ReviewerStatus.ACCEPTED,
    )
    d_new = phabdouble.diff(revision=r)
    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    diff = phabdouble.api_object_for(d_new, attachments={"commits": True})

    stack_state = create_state(revision)

    assert warning_reviews_not_current(revision, diff, stack_state) is not None


@pytest.mark.django_db
def test_warning_reviews_not_current_warns_on_unreviewed_revision(
    phabdouble, create_state  # noqa: ANN001
):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)
    # Don't create any reviewers.

    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    stack_state = create_state(revision)

    assert warning_reviews_not_current(revision, diff, stack_state) is not None


@pytest.mark.django_db
def test_warning_reviews_not_current_no_warning_on_accepted_diff(
    phabdouble, create_state  # noqa: ANN001
):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)
    phabdouble.reviewer(
        r,
        phabdouble.user(username="reviewer"),
        on_diff=d,
        status=ReviewerStatus.ACCEPTED,
    )

    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    stack_state = create_state(revision)

    assert warning_reviews_not_current(revision, diff, stack_state) is None


def test_confirmation_token_warning_order():
    warnings_a = [
        RevisionWarning(0, "W0", 123, "Details123"),
        RevisionWarning(0, "W0", 124, "Details124"),
        RevisionWarning(1, "W1", 123, "Details123"),
        RevisionWarning(3, "W3", 13, "Details3"),
        RevisionWarning(1000, "W1000", 13, "Details3"),
    ]
    warnings_b = [
        warnings_a[3],
        warnings_a[1],
        warnings_a[0],
        warnings_a[4],
        warnings_a[2],
    ]

    assert all(
        StackAssessment.confirmation_token(warnings_a)
        == StackAssessment.confirmation_token(w)
        for w in (warnings_b, reversed(warnings_a), reversed(warnings_b))
    )


# bug 1893453.
@pytest.mark.xfail
@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_simple_stack_saves_data_in_db(
    app,  # noqa: ANN001
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
    register_codefreeze_uri,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
):
    phabrepo = phabdouble.repo(name="mozilla-central")
    user = phabdouble.user(username="reviewer")

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabrepo)
    phabdouble.reviewer(r1, user)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabrepo, depends_on=[r1])
    phabdouble.reviewer(r2, user)

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabrepo, depends_on=[r2])
    phabdouble.reviewer(r3, user)

    response = proxy_client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
                {"revision_id": "D{}".format(r3["id"]), "diff_id": d3["id"]},
            ]
        },
        permissions=mock_permissions,
    )
    assert response.status_code == 202
    assert response.content_type == "application/json"
    assert "id" in response.json
    job_id = response.json["id"]

    # Get LandingJob object by its id
    job = LandingJob.objects.get(pk=job_id)
    assert job.id == job_id
    assert [
        (revision.revision_id, revision.diff_id) for revision in job.revisions.all()
    ] == [
        (r1["id"], d1["id"]),
        (r2["id"], d2["id"]),
        (r3["id"], d3["id"]),
    ]
    assert job.status == LandingJobStatus.SUBMITTED
    assert job.landed_revisions == {1: 1, 2: 2, 3: 3}


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_simple_partial_stack_saves_data_in_db(
    proxy_client,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
    register_codefreeze_uri,  # noqa: ANN001
):
    phabrepo = phabdouble.repo(name="mozilla-central")
    user = phabdouble.user(username="reviewer")

    # Create a stack with 3 revisions.
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabrepo)
    phabdouble.reviewer(r1, user)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabrepo, depends_on=[r1])
    phabdouble.reviewer(r2, user)

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabrepo, depends_on=[r2])
    phabdouble.reviewer(r3, user)

    # Request a transplant, but only for 2/3 revisions in the stack.
    response = proxy_client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
            ]
        },
        permissions=mock_permissions,
    )
    assert response.status_code == 202
    assert response.content_type == "application/json"
    assert "id" in response.json
    job_id = response.json["id"]

    # Get LandingJob object by its id
    job = LandingJob.objects.get(pk=job_id)
    assert job.id == job_id
    assert [(revision.revision_id, revision.diff_id) for revision in job.revisions] == [
        (r1["id"], d1["id"]),
        (r2["id"], d2["id"]),
    ]
    assert job.status == LandingJobStatus.SUBMITTED
    assert job.landed_revisions == {1: 1, 2: 2}


@pytest.mark.django_db
def test_integrated_transplant_records_approvers_peers_and_owners(
    proxy_client,  # noqa: ANN001
    treestatusdouble,  # noqa: ANN001
    hg_server,  # noqa: ANN001
    hg_clone,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
    register_codefreeze_uri,  # noqa: ANN001
    monkeypatch,  # noqa: ANN001
    normal_patch,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    checkin_project,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    hg_landing_worker,  # noqa: ANN001
    repo_mc,  # noqa: ANN001
):
    repo = repo_mc(SCM_TYPE_HG)
    treestatusdouble.open_tree(repo.name)
    hg_landing_worker.worker_instance.applicable_repos.add(repo)

    phabrepo = phabdouble.repo(name=repo.name)
    # Mock a few mots-related things needed by the landing worker.
    # First, mock path existance.
    mock_path = MagicMock()
    monkeypatch.setattr("lando.api.legacy.workers.landing_worker.Path", mock_path)
    (mock_path(repo.path) / "mots.yaml").exists.return_value = True

    # Then mock the directory/file config.
    mock_Directory = MagicMock()
    monkeypatch.setattr("lando.main.models.landing_job.Directory", mock_Directory)
    mock_Directory.return_value = MagicMock()
    mock_Directory().peers_and_owners = [101, 102]

    user = phabdouble.user(username="reviewer")
    user2 = phabdouble.user(username="reviewer2")

    d1 = phabdouble.diff(rawdiff=normal_patch(1))
    r1 = phabdouble.revision(diff=d1, repo=phabrepo)
    phabdouble.reviewer(r1, user)

    d2 = phabdouble.diff(rawdiff=normal_patch(2))
    r2 = phabdouble.revision(diff=d2, repo=phabrepo, depends_on=[r1])
    phabdouble.reviewer(r2, user2)

    response = proxy_client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
            ]
        },
        permissions=mock_permissions,
    )
    assert response.status_code == 202
    assert response.content_type == "application/json"
    assert "id" in response.json
    job_id = response.json["id"]

    # Get LandingJob object by its id
    job = LandingJob.objects.get(pk=job_id)
    assert job.id == job_id
    assert [
        (revision.revision_id, revision.diff_id) for revision in job.revisions.all()
    ] == [
        (r1["id"], d1["id"]),
        (r2["id"], d2["id"]),
    ]
    assert job.status == LandingJobStatus.SUBMITTED
    assert job.landed_revisions == {1: 1, 2: 2}
    approved_by = [revision.data["approved_by"] for revision in job.revisions.all()]
    assert approved_by == [[101], [102]]

    assert hg_landing_worker.run_job(job)
    assert job.status == LandingJobStatus.LANDED
    for revision in job.revisions.all():
        if revision.revision_id == 1:
            assert revision.data["peers_and_owners"] == [101]
        if revision.revision_id == 2:
            assert revision.data["peers_and_owners"] == [102]


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_updated_diff_id_reflected_in_landed_revisions(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
    register_codefreeze_uri,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
):
    """
    Perform a simple test but with two landing jobs for the same revision.

    The test is similar to the one in
    test_integrated_transplant_simple_stack_saves_data_in_db but submits an additional
    landing job for an updated revision diff.
    """
    repo = phabdouble.repo()
    user = phabdouble.user(username="reviewer")

    d1a = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1a, repo=repo)
    phabdouble.reviewer(r1, user)

    response = proxy_client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1a["id"]},
            ]
        },
        permissions=mock_permissions,
    )
    assert response.status_code == 202
    assert response.content_type == "application/json"
    assert "id" in response.json
    job_1_id = response.json["id"]

    # Get LandingJob object by its id.
    job = LandingJob.objects.get(pk=job_1_id)
    assert job.id == job_1_id
    assert [
        (revision.revision_id, revision.diff_id) for revision in job.revisions.all()
    ] == [
        (r1["id"], d1a["id"]),
    ]
    assert job.status == LandingJobStatus.SUBMITTED
    assert job.landed_revisions == {r1["id"]: d1a["id"]}

    # Cancel job.
    response = proxy_client.put(
        f"/landing_jobs/{job.id}",
        json={"status": "CANCELLED"},
        permissions=mock_permissions,
    )

    job = LandingJob.objects.get(pk=job_1_id)
    assert job.status == LandingJobStatus.CANCELLED

    d1b = phabdouble.diff(revision=r1)
    phabdouble.reviewer(r1, user)
    response = proxy_client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1b["id"]},
            ]
        },
        permissions=mock_permissions,
    )

    job_2_id = response.json["id"]

    # Get LandingJob objects by their ids.
    job_1 = LandingJob.objects.get(pk=job_1_id)
    job_2 = LandingJob.objects.get(pk=job_2_id)

    # The Revision objects always track the latest revisions.
    assert [
        (revision.revision_id, revision.diff_id) for revision in job_1.revisions.all()
    ] == [
        (r1["id"], d1b["id"]),
    ]

    assert [
        (revision.revision_id, revision.diff_id) for revision in job_2.revisions.all()
    ] == [
        (r1["id"], d1b["id"]),
    ]

    assert job_1.status == LandingJobStatus.CANCELLED
    assert job_2.status == LandingJobStatus.SUBMITTED

    assert job_1.landed_revisions == {r1["id"]: d1a["id"]}
    assert job_2.landed_revisions == {r1["id"]: d1b["id"]}


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_with_flags(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    monkeypatch,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    repo = phabdouble.repo(name="mozilla-new")
    user = phabdouble.user(username="reviewer")

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    phabdouble.reviewer(r1, user)

    test_flags = ["VALIDFLAG1", "VALIDFLAG2"]

    mock_format_commit_message = MagicMock()
    mock_format_commit_message.return_value = "Mock formatted commit message."
    monkeypatch.setattr(
        "lando.api.legacy.api.transplants.format_commit_message",
        mock_format_commit_message,
    )
    response = proxy_client.post(
        "/transplants",
        json={
            "flags": test_flags,
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ],
        },
        permissions=mock_permissions,
    )
    assert response.status_code == 202
    assert response.content_type == "application/json"
    assert mock_format_commit_message.call_count == 1
    assert test_flags in mock_format_commit_message.call_args[0]


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_with_invalid_flags(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    monkeypatch,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    repo = phabdouble.repo(name="mozilla-new")
    user = phabdouble.user(username="reviewer")

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    phabdouble.reviewer(r1, user)

    test_flags = ["VALIDFLAG1", "INVALIDFLAG"]
    response = proxy_client.post(
        "/transplants",
        json={
            "flags": test_flags,
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ],
        },
        permissions=mock_permissions,
    )
    assert response.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_legacy_repo_checkin_project_removed(
    phabdouble,  # noqa: ANN001
    checkin_project,  # noqa: ANN001
    proxy_client,  # noqa: ANN001
    monkeypatch,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
    register_codefreeze_uri,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
):
    repo = phabdouble.repo(name="mozilla-central")
    user = phabdouble.user(username="reviewer")

    d = phabdouble.diff()
    r = phabdouble.revision(diff=d, repo=repo, projects=[checkin_project])
    phabdouble.reviewer(r, user)

    mock_remove = MagicMock(admin_remove_phab_project)
    monkeypatch.setattr(
        "lando.api.legacy.api.transplants.admin_remove_phab_project", mock_remove
    )

    response = proxy_client.post(
        "/transplants",
        json={
            "landing_path": [{"revision_id": "D{}".format(r["id"]), "diff_id": d["id"]}]
        },
        permissions=mock_permissions,
    )
    assert response.status_code == 202
    assert mock_remove.apply_async.called
    _, call_kwargs = mock_remove.apply_async.call_args
    assert call_kwargs["args"] == (r["phid"], checkin_project["phid"])


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_repo_checkin_project_removed(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    checkin_project,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    monkeypatch,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    repo = phabdouble.repo(name="mozilla-new")
    user = phabdouble.user(username="reviewer")

    d = phabdouble.diff()
    r = phabdouble.revision(diff=d, repo=repo, projects=[checkin_project])
    phabdouble.reviewer(r, user)

    mock_remove = MagicMock(admin_remove_phab_project)
    monkeypatch.setattr(
        "lando.api.legacy.api.transplants.admin_remove_phab_project", mock_remove
    )

    response = proxy_client.post(
        "/transplants",
        json={
            "landing_path": [{"revision_id": "D{}".format(r["id"]), "diff_id": d["id"]}]
        },
        permissions=mock_permissions,
    )
    assert response.status_code == 202
    assert mock_remove.apply_async.called
    call_kwargs = mock_remove.apply_async.call_args[1]
    assert call_kwargs["args"] == (r["phid"], checkin_project["phid"])


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_without_auth0_permissions(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    repo = phabdouble.repo(name="mozilla-central")
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    response = proxy_client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        permissions=(),
    )

    assert response.status_code == 400
    assert (
        "You have insufficient permissions to land or your access has expired. "
        "main.scm_level_3 is required. See the FAQ for help."
    ) in response.json["blocker"]


@pytest.mark.django_db(transaction=True)
def test_transplant_wrong_landing_path_format(
    proxy_client, mock_permissions  # noqa: ANN001
):
    response = proxy_client.post(
        "/transplants",
        json={"landing_path": [{"revision_id": 1, "diff_id": 1}]},
        permissions=mock_permissions,
    )
    assert response.status_code == 400

    response = proxy_client.post(
        "/transplants",
        json={"landing_path": [{"revision_id": "1", "diff_id": 1}]},
        permissions=mock_permissions,
    )
    assert response.status_code == 400

    response = proxy_client.post(
        "/transplants",
        json={"landing_path": [{"revision_id": "D1"}]},
        permissions=mock_permissions,
    )
    assert response.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_diff_not_in_revision(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    repo = phabdouble.repo()
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    d2 = phabdouble.diff()
    phabdouble.revision(diff=d2, repo=repo)

    response = proxy_client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d2["id"]}
            ]
        },
        permissions=mock_permissions,
    )
    assert response.status_code == 400
    assert "A requested diff is not the latest." in response.json["blocker"]


@pytest.mark.django_db(transaction=True)
def test_transplant_nonexisting_revision_returns_404(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    response = proxy_client.post(
        "/transplants",
        json={"landing_path": [{"revision_id": "D1", "diff_id": 1}]},
        permissions=mock_permissions,
    )
    assert response.status_code == 404
    assert response.content_type == "application/problem+json"
    assert response.json["detail"] == "Stack Not Found"


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_revision_with_no_repo(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1)

    response = proxy_client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        permissions=mock_permissions,
    )
    assert response.status_code == 400
    assert "Landing repository is missing for this landing." in response.json["blocker"]


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_revision_with_unmapped_repo(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    repo = phabdouble.repo(name="notsupported")
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)

    response = proxy_client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        permissions=mock_permissions,
    )
    assert response.status_code == 400
    assert "Landing repository is missing for this landing." in response.json["blocker"]


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_sec_approval_group_is_excluded_from_reviewers_list(
    app,  # noqa: ANN001
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    sec_approval_project,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
    register_codefreeze_uri,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
):
    repo = phabdouble.repo()
    user = phabdouble.user(username="normal_reviewer")

    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=repo)
    phabdouble.reviewer(revision, user)
    phabdouble.reviewer(revision, sec_approval_project)

    response = proxy_client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(revision["id"]), "diff_id": diff["id"]}
            ]
        },
        permissions=mock_permissions,
    )
    assert response.status_code == 202

    # Check the transplanted patch for our alternate commit message.
    transplanted_patch = Revision.get_from_revision_id(revision["id"])
    assert transplanted_patch is not None, "Transplanted patch should be retrievable."
    assert sec_approval_project["name"] not in transplanted_patch.patch


@pytest.mark.django_db
def test_warning_wip_commit_message(phabdouble, create_state):  # noqa: ANN001
    revision = phabdouble.api_object_for(
        phabdouble.revision(
            title="WIP: Bug 123: test something r?reviewer",
            status=PhabricatorRevisionStatus.ACCEPTED,
        ),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(revision)

    assert warning_wip_commit_message(revision, {}, stack_state) is not None


def test_codefreeze_datetime_mock(codefreeze_datetime):  # noqa: ANN001
    dt = codefreeze_datetime()
    assert dt.now(tz=timezone.utc) == datetime(2000, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
    assert dt.strptime("tomorrow -0800", fmt="") == datetime(2000, 1, 6, 0, 0, 0)


@pytest.mark.django_db(transaction=True)
def test_unresolved_comment_warn(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    """Ensure a warning is generated when a revision has unresolved comments.

    This test sets up a revision and adds a resolved comment and dummy
    transaction. Sending a request should not generate a warning at this
    stage.

    Adding an unresolved comment and making the request again should
    generate a warning.
    """
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))
    phabdouble.transaction(
        transaction_type="inline",
        object=r1,
        comments=["this is done"],
        fields={"isDone": True},
    )
    # get_inline_comments should filter out unrelated transaction types.
    phabdouble.transaction("dummy", r1)

    response = proxy_client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        permissions=mock_permissions,
    )

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert not response.json[
        "warnings"
    ], "warnings should be empty for a revision without unresolved comments"

    phabdouble.transaction(
        transaction_type="inline",
        object=r1,
        comments=["this is not done"],
        fields={"isDone": False},
    )

    response = proxy_client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        permissions=mock_permissions,
    )

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.json[
        "warnings"
    ], "warnings should not be empty for a revision with unresolved comments"
    assert (
        response.json["warnings"][0]["id"] == 9
    ), "the warning ID should match the ID for warning_unresolved_comments"


@pytest.mark.django_db(transaction=True)
def test_unresolved_comment_stack(
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    """
    Ensure a warning is generated when a revision in the stack has unresolved comments.

    This test sets up a stack and adds a transaction to each revision, including
    unresolved comments and a dummy transaction.
    """
    repo = phabdouble.repo()
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=repo, depends_on=[r1])
    phabdouble.reviewer(r2, phabdouble.user(username="reviewer"))

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=repo, depends_on=[r2])
    phabdouble.reviewer(r3, phabdouble.user(username="reviewer"))

    phabdouble.transaction(
        transaction_type="inline",
        object=r1,
        comments=["this is not done"],
        fields={"isDone": False},
    )

    phabdouble.transaction(
        transaction_type="inline",
        object=r2,
        comments=["this is not done"],
        fields={"isDone": False},
    )

    phabdouble.transaction(
        transaction_type="inline",
        object=r3,
        comments=["this is done"],
        fields={"isDone": True},
    )

    # get_inline_comments should filter out unrelated transaction types.
    phabdouble.transaction("dummy", r3)

    response = proxy_client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
                {"revision_id": "D{}".format(r3["id"]), "diff_id": d3["id"]},
            ]
        },
        permissions=mock_permissions,
    )

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.json[
        "warnings"
    ], "warnings should not be empty for a stack with unresolved comments"
    assert (
        response.json["warnings"][0]["id"] == 9
    ), "the warning ID should match the ID for warning_unresolved_comments"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [
        s
        for s in PhabricatorRevisionStatus
        if s is not PhabricatorRevisionStatus.CHANGES_PLANNED
    ],
)
def test_check_author_planned_changes_changes_not_planned(
    phabdouble, status, create_state  # noqa: ANN001
):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=status),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    stack_state = create_state(revision)
    assert (
        blocker_author_planned_changes(
            revision=revision, diff={}, stack_state=stack_state
        )
        is None
    )


@pytest.mark.django_db
def test_check_author_planned_changes_changes_planned(
    phabdouble, create_state  # noqa: ANN001
):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=PhabricatorRevisionStatus.CHANGES_PLANNED),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    stack_state = create_state(revision)
    assert (
        blocker_author_planned_changes(
            revision=revision, diff={}, stack_state=stack_state
        )
        is not None
    )


@pytest.mark.django_db
@pytest.mark.parametrize("status", list(ReviewerStatus))
def test_relman_approval_status(
    status,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    create_state,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    """Check only an approval from relman allows landing"""
    repo = phabdouble.repo(name="uplift-target")
    repos = Repo.get_mapping()
    assert repos["uplift-target"].approval_required is True

    # Add relman as reviewer with specified status
    revision = phabdouble.revision(repo=repo, uplift="blah blah")
    phabdouble.reviewer(
        revision,
        release_management_project,
        status=status,
    )

    # Add a some extra reviewers
    for i in range(3):
        phabdouble.reviewer(revision, phabdouble.user(username=f"reviewer-{i}"))

    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(phab_revision)
    output = blocker_uplift_approval(
        revision=phab_revision, diff={}, stack_state=stack_state
    )
    if status == ReviewerStatus.ACCEPTED:
        assert output is None
    else:
        assert output == (
            "The release-managers group did not accept the stack: you need to wait "
            "for a group approval from release-managers, or request a new review."
        )


@pytest.mark.django_db
def test_relman_approval_missing(
    phabdouble,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    create_state,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    """A repo with an approval required needs relman as reviewer"""
    repo = phabdouble.repo(name="uplift-target")
    repos = Repo.get_mapping()
    assert repos["uplift-target"].approval_required is True

    revision = phabdouble.revision(repo=repo)
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(phab_revision)
    assert blocker_uplift_approval(
        revision=phab_revision, diff={}, stack_state=stack_state
    ) == (
        "The release-managers group did not accept the stack: "
        "you need to wait for a group approval from release-managers, "
        "or request a new review."
    )


@pytest.mark.django_db
def test_revision_has_data_classification_tag(
    phabdouble, create_state, needs_data_classification_project  # noqa: ANN001
):
    repo = phabdouble.repo()
    revision = phabdouble.revision(
        repo=repo, projects=[needs_data_classification_project]
    )
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(phab_revision)

    assert blocker_revision_data_classification(
        revision=phab_revision, diff={}, stack_state=stack_state
    ) == (
        "Revision makes changes to data collection and "
        "should have its data classification assessed before landing."
    ), "Revision with data classification project tag should be blocked from landing."

    revision = phabdouble.revision(repo=repo)
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    stack_state = create_state(phab_revision)
    assert (
        blocker_revision_data_classification(
            revision=phab_revision, diff={}, stack_state=stack_state
        )
        is None
    ), "Revision with no data classification tag should not be blocked from landing."


SYMLINK_DIFF = """
diff --git a/blahfile_real b/blahfile_real
new file mode 100644
index 0000000..907b308
--- /dev/null
+++ b/blahfile_real
@@ -0,0 +1 @@
+blah
diff --git a/blahfile_symlink b/blahfile_symlink
new file mode 120000
index 0000000..55faaf5
--- /dev/null
+++ b/blahfile_symlink
@@ -0,0 +1 @@
+/home/sheehan/blahfile
""".lstrip()


@pytest.mark.django_db
def test_blocker_prevent_symlinks(phabdouble, create_state):  # noqa: ANN001
    repo = phabdouble.repo()

    # Create a revision/diff pair without a symlink.
    revision = phabdouble.revision(repo=repo)
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff_normal = phabdouble.diff(revision=revision)

    # Create a revision/diff pair with a symlink.
    revision_symlink = phabdouble.revision(repo=repo, depends_on=[revision])
    phab_revision_symlink = phabdouble.api_object_for(
        revision_symlink,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff_symlink = phabdouble.diff(rawdiff=SYMLINK_DIFF, revision=revision_symlink)

    stack_state = create_state(phab_revision_symlink)

    assert (
        blocker_prevent_symlinks(
            revision=phab_revision, diff=diff_normal, stack_state=stack_state
        )
        is None
    ), "Diff without symlinks present should pass the check."

    assert (
        blocker_prevent_symlinks(
            revision=phab_revision_symlink, diff=diff_symlink, stack_state=stack_state
        )
        == "Revision introduces symlinks in the files `blahfile_symlink`."
    ), "Diff with symlinks present should fail the check."


TRY_TASK_CONFIG_DIFF = """
diff --git a/blah.json b/blah.json
new file mode 100644
index 0000000..663cbc2
--- /dev/null
+++ b/blah.json
@@ -0,0 +1 @@
+{"123":"456"}
diff --git a/try_task_config.json b/try_task_config.json
new file mode 100644
index 0000000..e44d36d
--- /dev/null
+++ b/try_task_config.json
@@ -0,0 +1 @@
+{"env": {"TRY_SELECTOR": "fuzzy"}, "version": 1, "tasks": ["source-test-cram-tryselect"]}
""".lstrip()


@pytest.mark.django_db
def test_blocker_try_task_config_no_landing_state(
    phabdouble, mocked_repo_config, create_state  # noqa: ANN001
):
    repo = phabdouble.repo()

    revision = phabdouble.revision(repo=repo)
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff = phabdouble.diff(revision=revision, rawdiff=TRY_TASK_CONFIG_DIFF)

    stack_state = create_state(phab_revision)

    assert (
        blocker_try_task_config(
            revision=phab_revision, diff=diff, stack_state=stack_state
        )
        == "Revision introduces the `try_task_config.json` file."
    ), "`try_task_config.json` should be rejected."


@pytest.mark.django_db
def test_blocker_try_task_config_landing_state_non_try(
    phabdouble, mocked_repo_config, create_state  # noqa: ANN001
):
    repo = phabdouble.repo()

    revision = phabdouble.revision(repo=repo)
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff = phabdouble.diff(revision=revision, rawdiff=TRY_TASK_CONFIG_DIFF)

    stack_state = create_state(phab_revision)

    assert (
        blocker_try_task_config(
            revision=phab_revision, diff=diff, stack_state=stack_state
        )
        == "Revision introduces the `try_task_config.json` file."
    ), "`try_task_config.json` should be rejected."


@pytest.mark.django_db
def test_warning_multiple_authors(
    phabdouble, mocked_repo_config, create_state  # noqa: ANN001
):
    repo = phabdouble.repo()

    # Create two users.
    alice = phabdouble.user(username="alice")
    bob = phabdouble.user(username="bob")

    # Create one revision.
    revision = phabdouble.revision(repo=repo, author=alice)

    # Create multiple diffs on the revision, one from each author.
    phabdouble.diff(revision=revision, author=alice)
    diff2 = phabdouble.diff(revision=revision, author=bob)

    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(phab_revision)

    warning = warning_multiple_authors(phab_revision, diff2, stack_state)
    assert warning is not None
    assert (
        warning.details == "Revision has multiple authors: alice, bob."
    ), "Multiple authors on a revision should return a warning."


@pytest.mark.django_db(transaction=True)
def test_transplant_on_linked_legacy_repo(
    app,  # noqa: ANN001
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    treestatusdouble,  # noqa: ANN001
    register_codefreeze_uri,  # noqa: ANN001
    mocked_repo_config,  # noqa: ANN001
    mock_permissions,  # noqa: ANN001
    repo_mc,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
):
    new_repo = repo_mc(SCM_TYPE_GIT)
    new_repo.legacy_source = Repo.objects.get(name="mozilla-central")
    new_repo.save()
    phabrepo = phabdouble.repo(name="mozilla-central")
    user = phabdouble.user(username="reviewer")

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabrepo)
    phabdouble.reviewer(r1, user)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabrepo, depends_on=[r1])
    phabdouble.reviewer(r2, user)

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabrepo, depends_on=[r2])

    phabdouble.reviewer(r3, user)
    response = proxy_client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
                {"revision_id": "D{}".format(r3["id"]), "diff_id": d3["id"]},
            ]
        },
        permissions=mock_permissions,
    )
    assert response.status_code == 202
    assert response.content_type == "application/json"
    assert "id" in response.json
    job_id = response.json["id"]

    # Get LandingJob object by its id
    job = LandingJob.objects.get(pk=job_id)
    assert job.id == job_id
    assert [
        (revision.revision_id, revision.diff_id) for revision in job.revisions.all()
    ] == [
        (r1["id"], d1["id"]),
        (r2["id"], d2["id"]),
        (r3["id"], d3["id"]),
    ]
    assert job.status == LandingJobStatus.SUBMITTED
    assert job.target_repo == new_repo
    assert job.landed_revisions == {1: 1, 2: 2, 3: 3}
