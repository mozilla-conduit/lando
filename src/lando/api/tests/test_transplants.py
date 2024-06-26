# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from lando.api.legacy.hg import HgRepo
from lando.api.legacy.mocks.canned_responses.auth0 import CANNED_USERINFO
from lando.api.legacy.phabricator import PhabricatorRevisionStatus, ReviewerStatus
from lando.api.legacy.repos import DONTBUILD, SCM_CONDUIT, SCM_LEVEL_3, Repo
from lando.api.legacy.reviews import get_collated_reviewers
from lando.api.legacy.transplants import (
    RevisionWarning,
    TransplantAssessment,
    warning_not_accepted,
    warning_previously_landed,
    warning_reviews_not_current,
    warning_revision_secure,
    warning_wip_commit_message,
)
from lando.api.legacy.workers.landing_worker import LandingWorker
from lando.main.models.landing_job import (
    LandingJob,
    LandingJobStatus,
    add_job_with_revisions,
)
from lando.main.models.revision import Revision
from lando.utils.tasks import admin_remove_phab_project


def _create_landing_job(
    *,
    landing_path=((1, 1),),
    revisions=None,
    requester_email="tuser@example.com",
    repository_name="mozilla-central",
    repository_url="http://hg.test",
    status=None,
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
    landing_path=((1, 1),),
    revisions=None,
    requester_email="tuser@example.com",
    repository_name="mozilla-central",
    repository_url="http://hg.test",
    status=None,
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
    job.revision_order = [str(revision.revision_id) for r in revisions]
    job.save()
    return job


@pytest.mark.django_db(transaction=True)
def test_dryrun_no_warnings_or_blockers(
    proxy_client, phabdouble, auth0_mock, mocked_repo_config
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
        headers=auth0_mock.mock_headers,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    expected_json = {"confirmation_token": None, "warnings": [], "blocker": None}
    assert response.json == expected_json


@pytest.mark.django_db(transaction=True)
def test_dryrun_invalid_path_blocks(proxy_client, phabdouble, auth0_mock):
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
        headers=auth0_mock.mock_headers,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    assert response.json["blocker"] is not None


@pytest.mark.django_db(transaction=True)
def test_dryrun_in_progress_transplant_blocks(
    proxy_client, phabdouble, auth0_mock, mocked_repo_config
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
        headers=auth0_mock.mock_headers,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    assert response.json["blocker"] == (
        "A landing for revisions in this stack is already in progress."
    )


@pytest.mark.django_db(transaction=True)
def test_dryrun_reviewers_warns(
    proxy_client, phabdouble, auth0_mock, mocked_repo_config
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
        headers=auth0_mock.mock_headers,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    assert response.json["warnings"]
    assert response.json["warnings"][0]["id"] == 0
    assert response.json["confirmation_token"] is not None


@pytest.mark.django_db(transaction=True)
def test_dryrun_codefreeze_warn(
    proxy_client,
    phabdouble,
    auth0_mock,
    codefreeze_datetime,
    monkeypatch,
    request_mocker,
    mocked_repo_config,
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
    mc_repo = Repo(
        tree="mozilla-conduit",
        url="https://hg.test/mozilla-conduit",
        access_group=SCM_CONDUIT,
        commit_flags=[DONTBUILD],
        product_details_url=product_details,
    )
    mc_mock = MagicMock()
    mc_mock.return_value = {"mozilla-central": mc_repo}
    monkeypatch.setattr("lando.api.legacy.transplants.get_repos_for_env", mc_mock)

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
        headers=auth0_mock.mock_headers,
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
    proxy_client,
    phabdouble,
    auth0_mock,
    codefreeze_datetime,
    monkeypatch,
    request_mocker,
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
    mc_repo = Repo(
        tree="mozilla-conduit",
        url="https://hg.test/mozilla-conduit",
        access_group=SCM_CONDUIT,
        commit_flags=[DONTBUILD],
        product_details_url=product_details,
    )
    mc_mock = MagicMock()
    mc_mock.return_value = {"mozilla-central": mc_repo}
    monkeypatch.setattr("lando.api.legacy.transplants.get_repos_for_env", mc_mock)

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
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert not response.json["warnings"]


# auth related issue, blockers empty.
@pytest.mark.xfail
@pytest.mark.parametrize(
    "userinfo,status,blocker",
    [
        (
            CANNED_USERINFO["NO_CUSTOM_CLAIMS"],
            200,
            "You have insufficient permissions to land. Level 3 "
            "Commit Access is required. See the FAQ for help.",
        ),
        (CANNED_USERINFO["EXPIRED_L3"], 200, "Your Level 3 Commit Access has expired."),
        (
            CANNED_USERINFO["UNVERIFIED_EMAIL"],
            200,
            "You do not have a Mozilla verified email address.",
        ),
    ],
)
@pytest.mark.django_db(transaction=True)
def test_integrated_dryrun_blocks_for_bad_userinfo(
    proxy_client,
    auth0_mock,
    phabdouble,
    userinfo,
    status,
    blocker,
    mocked_repo_config,
):
    auth0_mock.userinfo = userinfo
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())

    response = proxy_client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
        content_type="application/json",
    )

    assert response.status_code == status
    assert response.json["blocker"] == blocker


@pytest.mark.django_db(transaction=True)
def test_get_transplants_for_entire_stack(proxy_client, phabdouble):
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
    # assert response.status_code == 200
    assert len(response) == 4

    tmap = {i["id"]: i for i in response}
    assert t_not_in_stack.id not in tmap
    assert all(t.id in tmap for t in (t1, t2, t3, t4))


@pytest.mark.django_db(transaction=True)
def test_get_transplant_from_middle_revision(proxy_client, phabdouble):
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
    # assert response.status_code == 200
    assert len(response) == 1
    assert response[0]["id"] == t.id


@pytest.mark.django_db(transaction=True)
def test_get_transplant_not_authorized_to_view_revision(proxy_client, phabdouble):
    # Create a transplant pointing at a revision that will not
    # be returned by phabricator.
    _create_landing_job(landing_path=[(1, 1)], status=LandingJobStatus.SUBMITTED)
    response = proxy_client.get("/transplants?stack_revision_id=D1")
    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_warning_previously_landed_no_landings(phabdouble):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)
    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    diff = phabdouble.api_object_for(d, attachments={"commits": True})
    assert warning_previously_landed(revision=revision, diff=diff) is None


@pytest.mark.parametrize(
    "create_landing_job",
    (_create_landing_job, _create_landing_job_with_no_linked_revisions),
)
@pytest.mark.django_db(transaction=True)
def test_warning_previously_landed_failed_landing(phabdouble, create_landing_job):
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

    assert warning_previously_landed(revision=revision, diff=diff) is None


@pytest.mark.parametrize(
    "create_landing_job",
    (_create_landing_job, _create_landing_job_with_no_linked_revisions),
)
@pytest.mark.django_db(transaction=True)
def test_warning_previously_landed_landed_landing(phabdouble, create_landing_job):
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

    assert warning_previously_landed(revision=revision, diff=diff) is not None


def test_warning_revision_secure_project_none(phabdouble):
    revision = phabdouble.api_object_for(
        phabdouble.revision(),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    assert warning_revision_secure(revision=revision, secure_project_phid=None) is None


def test_warning_revision_secure_is_secure(phabdouble, secure_project):
    revision = phabdouble.api_object_for(
        phabdouble.revision(projects=[secure_project]),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    assert (
        warning_revision_secure(
            revision=revision, secure_project_phid=secure_project["phid"]
        )
        is not None
    )


def test_warning_revision_secure_is_not_secure(phabdouble, secure_project):
    not_secure_project = phabdouble.project("not_secure_project")
    revision = phabdouble.api_object_for(
        phabdouble.revision(projects=[not_secure_project]),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    assert (
        warning_revision_secure(
            revision=revision, secure_project_phid=secure_project["phid"]
        )
        is None
    )


@pytest.mark.parametrize(
    "status",
    [
        s
        for s in PhabricatorRevisionStatus
        if s is not PhabricatorRevisionStatus.ACCEPTED
    ],
)
def test_warning_not_accepted_warns_on_other_status(phabdouble, status):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=status),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    assert warning_not_accepted(revision=revision) is not None


def test_warning_not_accepted_no_warning_when_accepted(phabdouble):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=PhabricatorRevisionStatus.ACCEPTED),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    assert warning_not_accepted(revision=revision) is None


def test_warning_reviews_not_current_warns_on_unreviewed_diff(phabdouble):
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
    reviewers = get_collated_reviewers(revision)
    diff = phabdouble.api_object_for(d_new, attachments={"commits": True})

    assert (
        warning_reviews_not_current(revision=revision, diff=diff, reviewers=reviewers)
        is not None
    )


def test_warning_reviews_not_current_warns_on_unreviewed_revision(phabdouble):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)
    # Don't create any reviewers.

    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    reviewers = get_collated_reviewers(revision)
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    assert (
        warning_reviews_not_current(revision=revision, diff=diff, reviewers=reviewers)
        is not None
    )


def test_warning_reviews_not_current_no_warning_on_accepted_diff(phabdouble):
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
    reviewers = get_collated_reviewers(revision)
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    assert (
        warning_reviews_not_current(revision=revision, diff=diff, reviewers=reviewers)
        is None
    )


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
        TransplantAssessment.confirmation_token(warnings_a)
        == TransplantAssessment.confirmation_token(w)
        for w in (warnings_b, reversed(warnings_a), reversed(warnings_b))
    )


# bug 1893453.
@pytest.mark.xfail
@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_simple_stack_saves_data_in_db(
    app,
    proxy_client,
    phabdouble,
    auth0_mock,
    register_codefreeze_uri,
    mocked_repo_config,
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
        headers=auth0_mock.mock_headers,
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


# malformed patch, likely due to temporary changes to patch template
@pytest.mark.xfail
@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_records_approvers_peers_and_owners(
    mocked_repo_config,
    proxy_client,
    hg_server,
    hg_clone,
    treestatusdouble,
    auth0_mock,
    register_codefreeze_uri,
    monkeypatch,
    normal_patch,
    phabdouble,
    checkin_project,
):
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")
    repo = Repo(
        tree="mozilla-central",
        url=hg_server,
        access_group=SCM_LEVEL_3,
        push_path=hg_server,
        pull_path=hg_server,
    )
    phabrepo = phabdouble.repo(name="mozilla-central")
    hgrepo = HgRepo(hg_clone.strpath)

    # Mock a few mots-related things needed by the landing worker.
    # First, mock path existance.
    mock_path = MagicMock()
    monkeypatch.setattr("lando.api.legacy.workers.landing_worker.Path", mock_path)
    (mock_path(hgrepo.path) / "mots.yaml").exists.return_value = True

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
        headers=auth0_mock.mock_headers,
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

    worker = LandingWorker(sleep_seconds=0.01)
    assert worker.run_job(job, repo, hgrepo, treestatus)
    for revision in job.revisions.all():
        if revision.revision_id == 1:
            assert revision.data["peers_and_owners"] == [101]
        if revision.revision_id == 2:
            assert revision.data["peers_and_owners"] == [102]


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_updated_diff_id_reflected_in_landed_revisions(
    proxy_client,
    phabdouble,
    auth0_mock,
    register_codefreeze_uri,
    mocked_repo_config,
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
        headers=auth0_mock.mock_headers,
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
        headers=auth0_mock.mock_headers,
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
        headers=auth0_mock.mock_headers,
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
    proxy_client, phabdouble, auth0_mock, monkeypatch, mocked_repo_config
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
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 202
    assert response.content_type == "application/json"
    assert mock_format_commit_message.call_count == 1
    assert test_flags in mock_format_commit_message.call_args[0]


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_with_invalid_flags(
    proxy_client, phabdouble, auth0_mock, monkeypatch, mocked_repo_config
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
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_legacy_repo_checkin_project_removed(
    phabdouble,
    checkin_project,
    proxy_client,
    auth0_mock,
    register_codefreeze_uri,
    mocked_repo_config,
    monkeypatch,
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
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 202
    assert mock_remove.apply_async.called
    _, call_kwargs = mock_remove.apply_async.call_args
    assert call_kwargs["args"] == (r["phid"], checkin_project["phid"])


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_repo_checkin_project_removed(
    proxy_client,
    phabdouble,
    auth0_mock,
    checkin_project,
    mocked_repo_config,
    monkeypatch,
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
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 202
    assert mock_remove.apply_async.called
    call_kwargs = mock_remove.apply_async.call_args[1]
    assert call_kwargs["args"] == (r["phid"], checkin_project["phid"])


# Need to fix test fixtures to support auth
@pytest.mark.xfail
@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_without_auth0_permissions(
    proxy_client, auth0_mock, phabdouble, mocked_repo_config
):
    auth0_mock.userinfo = CANNED_USERINFO["NO_CUSTOM_CLAIMS"]

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
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 400
    assert response.json["blocker"] == (
        "You have insufficient permissions to land. "
        "Level 3 Commit Access is required. See the FAQ for help."
    )


@pytest.mark.django_db(transaction=True)
def test_transplant_wrong_landing_path_format(proxy_client, auth0_mock):
    response = proxy_client.post(
        "/transplants",
        json={"landing_path": [{"revision_id": 1, "diff_id": 1}]},
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400

    response = proxy_client.post(
        "/transplants",
        json={"landing_path": [{"revision_id": "1", "diff_id": 1}]},
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400

    response = proxy_client.post(
        "/transplants",
        json={"landing_path": [{"revision_id": "D1"}]},
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400


# Need to figure out why this is failing
@pytest.mark.skip
@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_diff_not_in_revision(
    proxy_client,
    phabdouble,
    auth0_mock,
    mocked_repo_config,
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
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400
    assert response.json["blocker"] == "A requested diff is not the latest."


@pytest.mark.django_db(transaction=True)
def test_transplant_nonexisting_revision_returns_404(
    proxy_client, phabdouble, auth0_mock
):
    response = proxy_client.post(
        "/transplants",
        json={"landing_path": [{"revision_id": "D1", "diff_id": 1}]},
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 404
    assert response.content_type == "application/problem+json"
    assert response.json["title"] == "Stack Not Found"


# Also broken likely same issue as test_integrated_transplant_diff_not_in_revision
@pytest.mark.skip
@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_revision_with_no_repo(
    proxy_client, phabdouble, auth0_mock
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
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400
    assert response.json["title"] == "Landing is Blocked"
    assert response.json["blocker"] == (
        "The requested set of revisions are not landable."
    )


# Also broken likely same issue as test_integrated_transplant_diff_not_in_revision
@pytest.mark.skip
@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_revision_with_unmapped_repo(
    proxy_client, phabdouble, auth0_mock
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
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400
    assert response.json["title"] == "Landing is Blocked"
    assert response.json["blocker"] == (
        "The requested set of revisions are not landable."
    )


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_sec_approval_group_is_excluded_from_reviewers_list(
    app,
    proxy_client,
    phabdouble,
    auth0_mock,
    sec_approval_project,
    register_codefreeze_uri,
    mocked_repo_config,
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
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 202

    # Check the transplanted patch for our alternate commit message.
    transplanted_patch = Revision.get_from_revision_id(revision["id"])
    assert transplanted_patch is not None, "Transplanted patch should be retrievable."
    assert sec_approval_project["name"] not in transplanted_patch.patch_string


def test_warning_wip_commit_message(phabdouble):
    revision = phabdouble.api_object_for(
        phabdouble.revision(
            title="WIP: Bug 123: test something r?reviewer",
            status=PhabricatorRevisionStatus.ACCEPTED,
        ),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    assert warning_wip_commit_message(revision=revision) is not None


def test_codefreeze_datetime_mock(codefreeze_datetime):
    dt = codefreeze_datetime()
    assert dt.now(tz=timezone.utc) == datetime(2000, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
    assert dt.strptime("tomorrow -0800", fmt="") == datetime(2000, 1, 6, 0, 0, 0)


@pytest.mark.django_db(transaction=True)
def test_unresolved_comment_warn(
    proxy_client,
    phabdouble,
    auth0_mock,
    mocked_repo_config,
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
        headers=auth0_mock.mock_headers,
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
        headers=auth0_mock.mock_headers,
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
    proxy_client,
    phabdouble,
    auth0_mock,
    mocked_repo_config,
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
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.json[
        "warnings"
    ], "warnings should not be empty for a stack with unresolved comments"
    assert (
        response.json["warnings"][0]["id"] == 9
    ), "the warning ID should match the ID for warning_unresolved_comments"
