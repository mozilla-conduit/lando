import json
from datetime import datetime, timezone
from unittest import mock
from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import Permission
from typing_extensions import Any, Callable

from lando.api.legacy.api import transplants as legacy_api_transplants
from lando.api.legacy.transplants import (
    RevisionWarning,
    StackAssessment,
    blocker_author_planned_changes,
    blocker_prevent_nsprnss_files,
    blocker_prevent_submodules,
    blocker_prevent_symlinks,
    blocker_revision_data_classification,
    blocker_try_task_config,
    blocker_uplift_approval,
    blocker_user_scm_level,
    warning_multiple_authors,
    warning_not_accepted,
    warning_previously_landed,
    warning_reviews_not_current,
    warning_revision_secure,
    warning_wip_commit_message,
)
from lando.api.tests.mocks import PhabricatorDouble
from lando.main.models import (
    DONTBUILD,
    SCM_CONDUIT,
    JobStatus,
    LandingJob,
    Repo,
)
from lando.main.models.revision import Revision
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG
from lando.main.support import LegacyAPIException
from lando.utils.phabricator import PhabricatorRevisionStatus, ReviewerStatus
from lando.utils.tasks import admin_remove_phab_project


@pytest.mark.django_db(transaction=True)
def test_dryrun_no_warnings_or_blockers(
    user,
    phabdouble,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))
    phabdouble.reviewer(r1, phabdouble.project("reviewer2"))

    result = legacy_api_transplants.dryrun(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
    )

    expected_json = {"confirmation_token": None, "warnings": [], "blocker": None}
    assert result == expected_json


@pytest.mark.django_db(transaction=True)
def test_dryrun_invalid_path_blocks(
    user,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    mocked_repo_config,
):
    d1 = phabdouble.diff()
    d2 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    r2 = phabdouble.revision(
        diff=d2, repo=phabdouble.repo(name="not-mozilla-central"), depends_on=[r1]
    )
    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))
    phabdouble.reviewer(r1, phabdouble.project("reviewer2"))

    result = legacy_api_transplants.dryrun(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
            ]
        },
    )

    assert (
        "Depends on D1 which is open and has a different repository"
        in result["blocker"]
    )


@pytest.mark.django_db
def test_dryrun_published_parent(
    user,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    mocked_repo_config,
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

    result = legacy_api_transplants.dryrun(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
            ]
        },
    )

    assert result["blocker"] is None


@pytest.mark.django_db
def test_dryrun_open_parent(
    user,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
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

    result = legacy_api_transplants.dryrun(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                # Set the landing path to try and land only r2, despite r1 being open
                # and part of the stack.
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
            ]
        },
    )

    assert (
        "The requested set of revisions are not landable." in result["blocker"]
    ), "Landing should be blocked due to r1 still being open and part of the stack."


@pytest.mark.django_db(transaction=True)
def test_dryrun_in_progress_transplant_blocks(
    user,
    phabdouble,
    make_landing_job,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
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
    make_landing_job(
        landing_path=[(r1["id"], d1["id"])],
        status=JobStatus.SUBMITTED,
    )

    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))
    phabdouble.reviewer(r1, phabdouble.project("reviewer2"))

    result = legacy_api_transplants.dryrun(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
    )

    assert result["blocker"] == (
        "A landing for revisions in this stack is already in progress."
    )


@pytest.mark.django_db(transaction=True)
def test_dryrun_reviewers_warns(
    user,
    phabdouble,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(
        r1, phabdouble.user(username="reviewer"), status=ReviewerStatus.REJECTED
    )

    result = legacy_api_transplants.dryrun(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
    )

    assert result["warnings"]
    assert result["confirmation_token"] is not None


@pytest.mark.django_db(transaction=True)
def test_dryrun_codefreeze_warn(
    user,
    phabdouble,
    codefreeze_datetime,
    monkeypatch,
    request_mocker,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
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

    result = legacy_api_transplants.dryrun(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
    )

    assert result[
        "warnings"
    ], "warnings should not be empty for a repo under code freeze"
    assert (
        result["warnings"][0]["display"] == "Repository is under a soft code freeze."
    ), "the warning display should match warning_code_freeze"
    assert result["confirmation_token"] is not None


@pytest.mark.django_db(transaction=True)
def test_dryrun_outside_codefreeze(
    user,
    phabdouble,
    codefreeze_datetime,
    monkeypatch,
    request_mocker,
    release_management_project,
    needs_data_classification_project,
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

    result = legacy_api_transplants.dryrun(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
    )

    assert not result["warnings"]


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
    user,
    phabdouble,
    permissions,
    status,
    blocker,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())

    result = legacy_api_transplants.dryrun(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
    )

    assert blocker in result["blocker"]


@pytest.mark.django_db(transaction=True)
def test_get_transplants_for_entire_stack(phabdouble, make_landing_job, repo_mc):
    d1a = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1a, repo=phabdouble.repo())
    d1b = phabdouble.diff(revision=r1)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabdouble.repo(), depends_on=[r1])

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabdouble.repo(), depends_on=[r1])

    d_not_in_stack = phabdouble.diff()
    r_not_in_stack = phabdouble.revision(diff=d_not_in_stack, repo=phabdouble.repo())

    repo = repo_mc(SCM_TYPE_GIT)

    t1 = make_landing_job(
        target_repo=repo,
        landing_path=[(r1["id"], d1a["id"])],
        status=JobStatus.FAILED,
    )
    t2 = make_landing_job(
        target_repo=repo,
        landing_path=[(r1["id"], d1b["id"])],
        status=JobStatus.LANDED,
    )
    t3 = make_landing_job(
        target_repo=repo,
        landing_path=[(r2["id"], d2["id"])],
        status=JobStatus.SUBMITTED,
    )
    t4 = make_landing_job(
        target_repo=repo,
        landing_path=[(r3["id"], d3["id"])],
        status=JobStatus.LANDED,
    )

    t_not_in_stack = make_landing_job(
        target_repo=repo,
        landing_path=[(r_not_in_stack["id"], d_not_in_stack["id"])],
        status=JobStatus.LANDED,
    )

    result = legacy_api_transplants.get_list(
        phabdouble.get_phabricator_client(), stack_revision_id=f"D{r2['id']}"
    )
    assert len(result) == 4

    tmap = {i.id: i for i in result}
    assert t_not_in_stack.id not in tmap
    assert all(t.id in tmap for t in (t1, t2, t3, t4))


@pytest.mark.django_db(transaction=True)
def test_get_transplant_from_middle_revision(phabdouble, make_landing_job):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabdouble.repo(), depends_on=[r1])

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabdouble.repo(), depends_on=[r1])

    t = make_landing_job(
        landing_path=[(r1["id"], d1["id"]), (r2["id"], d2["id"]), (r3["id"], d3["id"])],
        status=JobStatus.FAILED,
    )

    result = legacy_api_transplants.get_list(
        phabdouble.get_phabricator_client(), stack_revision_id=f"D{r2['id']}"
    )
    assert len(result) == 1
    assert result[0].id == t.id


@pytest.mark.django_db(transaction=True)
def test_get_transplant_not_authorized_to_view_revision(
    user, phabdouble, make_landing_job, repo_mc
):
    # Create a transplant pointing at a revision that will not
    # be returned by phabricator.
    make_landing_job(
        landing_path=[(1, 1)],
        status=JobStatus.SUBMITTED,
    )

    with pytest.raises(LegacyAPIException) as exc_info:
        legacy_api_transplants.get_list(
            phabdouble.get_phabricator_client(), stack_revision_id="D1"
        )
    assert exc_info.value.status == 404


@pytest.mark.django_db(transaction=True)
def test_warning_previously_landed_no_landings(phabdouble, create_state):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)
    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    diff = phabdouble.api_object_for(d, attachments={"commits": True})
    stack_state = create_state(revision)
    assert warning_previously_landed(revision, diff, stack_state) is None


@pytest.mark.django_db(transaction=True)
def test_warning_previously_landed_failed_landing(
    phabdouble, make_landing_job, create_state, repo_mc
):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)

    make_landing_job(
        target_repo=repo_mc(SCM_TYPE_GIT),
        landing_path=[(r["id"], d["id"])],
        status=JobStatus.FAILED,
    )

    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    stack_state = create_state(revision)

    assert warning_previously_landed(revision, diff, stack_state) is None


@pytest.mark.django_db(transaction=True)
def test_warning_previously_landed_landed_landing(
    phabdouble, make_landing_job, create_state, repo_mc
):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)

    make_landing_job(
        target_repo=repo_mc(SCM_TYPE_GIT),
        landing_path=[(r["id"], d["id"])],
        status=JobStatus.LANDED,
    )

    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    stack_state = create_state(revision)

    assert warning_previously_landed(revision, diff, stack_state) is not None


@pytest.mark.django_db
def test_warning_revision_secure_project_none(phabdouble, create_state):
    revision = phabdouble.api_object_for(
        phabdouble.revision(),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(revision)

    assert warning_revision_secure(revision, {}, stack_state) is None


@pytest.mark.django_db
def test_warning_revision_secure_is_secure(phabdouble, secure_project, create_state):
    revision = phabdouble.api_object_for(
        phabdouble.revision(projects=[secure_project]),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(revision)

    assert warning_revision_secure(revision, {}, stack_state) is not None


@pytest.mark.django_db
def test_warning_revision_secure_is_not_secure(
    phabdouble, secure_project, create_state
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
def test_warning_not_accepted_warns_on_other_status(phabdouble, status, create_state):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=status),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(revision)

    assert warning_not_accepted(revision, {}, stack_state) is not None


@pytest.mark.django_db
def test_warning_not_accepted_no_warning_when_accepted(phabdouble, create_state):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=PhabricatorRevisionStatus.ACCEPTED),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(revision)

    assert warning_not_accepted(revision, {}, stack_state) is None


@pytest.mark.django_db
def test_warning_reviews_not_current_warns_on_unreviewed_diff(phabdouble, create_state):
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
    phabdouble, create_state
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
    phabdouble, create_state
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
        RevisionWarning("W0", 123, "Details123"),
        RevisionWarning("W0", 124, "Details124"),
        RevisionWarning("W1", 123, "Details123"),
        RevisionWarning("W3", 13, "Details3"),
        RevisionWarning("W1000", 13, "Details3"),
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
    app,
    user,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    register_codefreeze_uri,
    mocked_repo_config,
):
    phabrepo = phabdouble.repo(name="mozilla-central")
    reviewer = phabdouble.user(username="reviewer")

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabrepo)
    phabdouble.reviewer(r1, reviewer)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabrepo, depends_on=[r1])
    phabdouble.reviewer(r2, reviewer)

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabrepo, depends_on=[r2])
    phabdouble.reviewer(r3, reviewer)

    result, status_code = legacy_api_transplants.post(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
                {"revision_id": "D{}".format(r3["id"]), "diff_id": d3["id"]},
            ]
        },
    )
    assert status_code == 202
    assert "id" in result
    job_id = result["id"]

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
    assert job.status == JobStatus.SUBMITTED
    assert job.landed_phabricator_revisions == {1: 1, 2: 2, 3: 3}


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_simple_partial_stack_saves_data_in_db(
    user,
    mocked_repo_config,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    register_codefreeze_uri,
):
    phabrepo = phabdouble.repo(name="mozilla-central")
    reviewer = phabdouble.user(username="reviewer")

    # Create a stack with 3 revisions.
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabrepo)
    phabdouble.reviewer(r1, reviewer)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabrepo, depends_on=[r1])
    phabdouble.reviewer(r2, reviewer)

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabrepo, depends_on=[r2])
    phabdouble.reviewer(r3, reviewer)

    # Request a transplant, but only for 2/3 revisions in the stack.

    result, status_code = legacy_api_transplants.post(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
            ]
        },
    )
    assert status_code == 202
    assert "id" in result
    job_id = result["id"]

    # Get LandingJob object by its id
    job = LandingJob.objects.get(pk=job_id)
    assert job.id == job_id
    assert [(revision.revision_id, revision.diff_id) for revision in job.revisions] == [
        (r1["id"], d1["id"]),
        (r2["id"], d2["id"]),
    ]
    assert job.status == JobStatus.SUBMITTED
    assert job.landed_phabricator_revisions == {1: 1, 2: 2}


@pytest.mark.django_db
def test_integrated_transplant_records_approvers_peers_and_owners(
    user,
    authenticated_client,
    treestatusdouble,
    hg_server,
    hg_clone,
    release_management_project,
    needs_data_classification_project,
    register_codefreeze_uri,
    monkeypatch,
    normal_patch,
    phabdouble,
    checkin_project,
    hg_landing_worker,
    repo_mc,
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

    reviewer = phabdouble.user(username="reviewer")
    user2 = phabdouble.user(username="reviewer2")

    d1 = phabdouble.diff(rawdiff=normal_patch(1))
    r1 = phabdouble.revision(diff=d1, repo=phabrepo)
    phabdouble.reviewer(r1, reviewer)

    d2 = phabdouble.diff(rawdiff=normal_patch(2))
    r2 = phabdouble.revision(diff=d2, repo=phabrepo, depends_on=[r1])
    phabdouble.reviewer(r2, user2)

    result, status_code = legacy_api_transplants.post(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
            ]
        },
    )
    assert status_code == 202
    assert "id" in result
    job_id = result["id"]

    # Get LandingJob object by its id
    job = LandingJob.objects.get(pk=job_id)
    assert job.id == job_id
    assert [
        (revision.revision_id, revision.diff_id) for revision in job.revisions.all()
    ] == [
        (r1["id"], d1["id"]),
        (r2["id"], d2["id"]),
    ]
    assert job.status == JobStatus.SUBMITTED
    assert job.landed_phabricator_revisions == {1: 1, 2: 2}
    approved_by = [revision.data["approved_by"] for revision in job.revisions.all()]
    assert approved_by == [[101], [102]]

    assert hg_landing_worker.run_job(job)
    assert job.landed_commit_id

    # Fetch Job data.
    response = authenticated_client.get(
        f"/landing_jobs/{job.id}",
        follow=True,
    )
    assert (
        response.status_code == 200
    ), f"Invalid status code from GET /landing_jobs/{job.id}"

    result = response.json()
    assert result["id"] == job.id, f"Invalid id in GET /landing_jobs/{job.id} response"
    assert (
        result["status"] == JobStatus.LANDED
    ), f"Invalid status in GET /landing_jobs/{job.id} response"
    assert (
        result["commit_id"] == job.landed_commit_id
    ), f"Invalid commit_id in GET /landing_jobs/{job.id} response"

    assert job.status == JobStatus.LANDED
    for revision in job.revisions.all():
        if revision.revision_id == 1:
            assert revision.data["peers_and_owners"] == [101]
        if revision.revision_id == 2:
            assert revision.data["peers_and_owners"] == [102]


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_updated_diff_id_reflected_in_landed_phabricator_revisions(
    user,
    authenticated_client,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
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
    reviewer = phabdouble.user(username="reviewer")

    d1a = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1a, repo=repo)
    phabdouble.reviewer(r1, reviewer)

    result, status_code = legacy_api_transplants.post(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1a["id"]},
            ]
        },
    )
    assert status_code == 202
    assert "id" in result
    job_1_id = result["id"]

    # Get LandingJob object by its id.
    job = LandingJob.objects.get(pk=job_1_id)
    assert job.id == job_1_id
    assert [
        (revision.revision_id, revision.diff_id) for revision in job.revisions.all()
    ] == [
        (r1["id"], d1a["id"]),
    ]
    assert job.status == JobStatus.SUBMITTED
    assert job.landed_phabricator_revisions == {r1["id"]: d1a["id"]}

    # Fetch JSON data.
    response = authenticated_client.get(
        f"/landing_jobs/{job.id}",
        follow=True,
    )
    assert (
        response.status_code == 200
    ), f"Invalid status code from GET /landing_jobs/{job.id}"

    result = response.json()
    assert result["id"] == job.id, f"Invalid id in GET /landing_jobs/{job.id} response"
    assert (
        result["status"] == JobStatus.SUBMITTED
    ), f"Invalid status in GET /landing_jobs/{job.id} response"

    # Cancel job.

    response = authenticated_client.put(
        f"/landing_jobs/{job.id}/",
        data=json.dumps({"status": "CANCELLED"}),
        content_type="application/json",
    )
    assert response.status_code == 200

    job = LandingJob.objects.get(pk=job_1_id)
    assert job.status == JobStatus.CANCELLED

    d1b = phabdouble.diff(revision=r1)
    phabdouble.reviewer(r1, reviewer)

    result, status_code = legacy_api_transplants.post(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1b["id"]},
            ]
        },
    )

    job_2_id = result["id"]

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

    assert job_1.status == JobStatus.CANCELLED
    assert job_2.status == JobStatus.SUBMITTED

    assert job_1.landed_phabricator_revisions == {r1["id"]: d1a["id"]}
    assert job_2.landed_phabricator_revisions == {r1["id"]: d1b["id"]}


@pytest.mark.django_db(transaction=True)
def test_get_landing_jobs_404(authenticated_client):
    # Fetch JSON data.
    response = authenticated_client.get(
        "/landing_jobs/20000",
        follow=True,
    )
    assert (
        response.status_code == 404
    ), "Incorrect status code from GET /landing_jobs/ for non-existent job"
    assert response.json()["title"] == "Landing job not found"
    assert response.json()["detail"] == "A landing job with ID 20000 was not found."


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_with_flags(
    user,
    phabdouble,
    monkeypatch,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
):
    repo = phabdouble.repo(name="mozilla-new")
    reviewer = phabdouble.user(username="reviewer")

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    phabdouble.reviewer(r1, reviewer)

    test_flags = ["VALIDFLAG1", "VALIDFLAG2"]

    mock_format_commit_message = MagicMock()
    mock_format_commit_message.return_value = "Mock formatted commit message."
    monkeypatch.setattr(
        "lando.api.legacy.api.transplants.format_commit_message",
        mock_format_commit_message,
    )

    result, status_code = legacy_api_transplants.post(
        phabdouble.get_phabricator_client(),
        user,
        {
            "flags": test_flags,
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ],
        },
    )
    assert status_code == 202
    assert mock_format_commit_message.call_count == 1
    assert test_flags in mock_format_commit_message.call_args[0]


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_with_invalid_flags(
    user,
    phabdouble,
    monkeypatch,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
):
    repo = phabdouble.repo(name="mozilla-new")
    reviewer = phabdouble.user(username="reviewer")

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    phabdouble.reviewer(r1, reviewer)

    test_flags = ["VALIDFLAG1", "INVALIDFLAG"]

    with pytest.raises(LegacyAPIException) as exc_info:
        legacy_api_transplants.post(
            phabdouble.get_phabricator_client(),
            user,
            {
                "flags": test_flags,
                "landing_path": [
                    {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
                ],
            },
        )
    assert exc_info.value.status == 400


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_legacy_repo_checkin_project_removed(
    phabdouble,
    checkin_project,
    user,
    monkeypatch,
    release_management_project,
    needs_data_classification_project,
    register_codefreeze_uri,
    mocked_repo_config,
):
    repo = phabdouble.repo(name="mozilla-central")
    reviewer = phabdouble.user(username="reviewer")

    d = phabdouble.diff()
    r = phabdouble.revision(diff=d, repo=repo, projects=[checkin_project])
    phabdouble.reviewer(r, reviewer)

    mock_remove = MagicMock(admin_remove_phab_project)
    monkeypatch.setattr(
        "lando.api.legacy.api.transplants.admin_remove_phab_project", mock_remove
    )

    result, status_code = legacy_api_transplants.post(
        phabdouble.get_phabricator_client(),
        user,
        {"landing_path": [{"revision_id": "D{}".format(r["id"]), "diff_id": d["id"]}]},
    )
    assert status_code == 202
    assert mock_remove.apply_async.called
    _, call_kwargs = mock_remove.apply_async.call_args
    assert call_kwargs["args"] == (r["phid"], checkin_project["phid"])


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_repo_checkin_project_removed(
    user,
    phabdouble,
    checkin_project,
    mocked_repo_config,
    monkeypatch,
    release_management_project,
    needs_data_classification_project,
):
    repo = phabdouble.repo(name="mozilla-new")
    reviewer = phabdouble.user(username="reviewer")

    d = phabdouble.diff()
    r = phabdouble.revision(diff=d, repo=repo, projects=[checkin_project])
    phabdouble.reviewer(r, reviewer)

    mock_remove = MagicMock(admin_remove_phab_project)
    monkeypatch.setattr(
        "lando.api.legacy.api.transplants.admin_remove_phab_project", mock_remove
    )

    result, status_code = legacy_api_transplants.post(
        phabdouble.get_phabricator_client(),
        user,
        {"landing_path": [{"revision_id": "D{}".format(r["id"]), "diff_id": d["id"]}]},
    )
    assert status_code == 202
    assert mock_remove.apply_async.called
    call_kwargs = mock_remove.apply_async.call_args[1]
    assert call_kwargs["args"] == (r["phid"], checkin_project["phid"])


@pytest.mark.django_db(transaction=True)
@pytest.mark.django_db
@pytest.mark.parametrize(
    "superuser,user_perms,group_perms",
    (
        (False, [], []),
        (False, [], ["scm_level_3"]),
        (True, [], []),
        (True, [], ["scm_level_3"]),
    ),
)
def test_integrated_transplant_without_permissions(
    scm_user: Callable,
    make_superuser: Callable,
    phabdouble: PhabricatorDouble,
    mocked_repo_config: mock.Mock,
    release_management_project: dict[str, Any],
    needs_data_classification_project: dict[str, Any],
    superuser: bool,
    user_perms: list[str],
    group_perms: list[str],
):
    """Test that a user without permissions gets blocked."""
    # Create a user with no permissions
    user_without_perms = scm_user(
        [Permission.objects.get(codename=perm) for perm in user_perms],
        "password",
        [Permission.objects.get(codename=perm) for perm in group_perms],
    )

    if superuser:
        user_without_perms = make_superuser(user_without_perms)

    repo = phabdouble.repo(name="mozilla-central")
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)

    with pytest.raises(LegacyAPIException) as exc_info:
        legacy_api_transplants.post(
            phabdouble.get_phabricator_client(),
            user_without_perms,
            {
                "landing_path": [
                    {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
                ]
            },
        )

    assert exc_info.value.status == 400
    assert (
        "You have insufficient permissions to land or your access has expired. "
        "main.scm_level_3 is required. See the FAQ for help."
    ) in exc_info.value.extra["blocker"]


@pytest.mark.django_db(transaction=True)
def test_transplant_wrong_landing_path_format(user, phabdouble):
    with pytest.raises(LegacyAPIException) as exc_info:
        legacy_api_transplants.post(
            phabdouble.get_phabricator_client(),
            user,
            {"landing_path": [{"revision_id": 1, "diff_id": 1}]},
        )
    assert exc_info.value.status == 400

    with pytest.raises(LegacyAPIException) as exc_info:
        legacy_api_transplants.post(
            phabdouble.get_phabricator_client(),
            user,
            {"landing_path": [{"revision_id": "1", "diff_id": 1}]},
        )
    assert exc_info.value.status == 400

    with pytest.raises(LegacyAPIException) as exc_info:
        legacy_api_transplants.post(
            phabdouble.get_phabricator_client(),
            user,
            {"landing_path": [{"revision_id": "D1"}]},
        )
    assert exc_info.value.status == 400


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_diff_not_in_revision(
    user,
    phabdouble,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
):
    repo = phabdouble.repo()
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    d2 = phabdouble.diff()
    phabdouble.revision(diff=d2, repo=repo)

    with pytest.raises(LegacyAPIException) as exc_info:
        legacy_api_transplants.post(
            phabdouble.get_phabricator_client(),
            user,
            {
                "landing_path": [
                    {"revision_id": "D{}".format(r1["id"]), "diff_id": d2["id"]}
                ]
            },
        )
    assert exc_info.value.status == 400
    assert "A requested diff is not the latest." in exc_info.value.extra["blocker"]


@pytest.mark.django_db(transaction=True)
def test_transplant_nonexisting_revision_returns_404(
    user,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
):
    with pytest.raises(LegacyAPIException) as exc_info:
        legacy_api_transplants.post(
            phabdouble.get_phabricator_client(),
            user,
            {"landing_path": [{"revision_id": "D1", "diff_id": 1}]},
        )
    assert exc_info.value.status == 404
    assert exc_info.value.json_detail["detail"] == "Stack Not Found"


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_revision_with_no_repo(
    user,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1)

    with pytest.raises(LegacyAPIException) as exc_info:
        legacy_api_transplants.post(
            phabdouble.get_phabricator_client(),
            user,
            {
                "landing_path": [
                    {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
                ]
            },
        )
    assert exc_info.value.status == 400
    assert (
        "Landing repository is missing for this landing."
        in exc_info.value.extra["blocker"]
    )


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_revision_with_unmapped_repo(
    user,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
):
    repo = phabdouble.repo(name="notsupported")
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)

    with pytest.raises(LegacyAPIException) as exc_info:
        legacy_api_transplants.post(
            phabdouble.get_phabricator_client(),
            user,
            {
                "landing_path": [
                    {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
                ]
            },
        )
    assert exc_info.value.status == 400
    assert (
        "Landing repository is missing for this landing."
        in exc_info.value.extra["blocker"]
    )


@pytest.mark.django_db(transaction=True)
def test_integrated_transplant_sec_approval_group_is_excluded_from_reviewers_list(
    app,
    user,
    phabdouble,
    sec_approval_project,
    release_management_project,
    needs_data_classification_project,
    register_codefreeze_uri,
    mocked_repo_config,
):
    repo = phabdouble.repo()
    reviewer = phabdouble.user(username="normal_reviewer")

    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=repo)
    phabdouble.reviewer(revision, reviewer)
    phabdouble.reviewer(revision, sec_approval_project)

    result, status_code = legacy_api_transplants.post(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(revision["id"]), "diff_id": diff["id"]}
            ]
        },
    )
    assert status_code == 202

    # Check the transplanted patch for our alternate commit message.
    transplanted_patch = Revision.get_from_revision_id(revision["id"])
    assert transplanted_patch is not None, "Transplanted patch should be retrievable."
    assert sec_approval_project["name"] not in transplanted_patch.patch


@pytest.mark.django_db
def test_warning_wip_commit_message(phabdouble, create_state):
    revision = phabdouble.api_object_for(
        phabdouble.revision(
            title="WIP: Bug 123: test something r?reviewer",
            status=PhabricatorRevisionStatus.ACCEPTED,
        ),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    stack_state = create_state(revision)

    assert warning_wip_commit_message(revision, {}, stack_state) is not None


def test_codefreeze_datetime_mock(codefreeze_datetime):
    dt = codefreeze_datetime()
    assert dt.now(tz=timezone.utc) == datetime(2000, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
    assert dt.strptime("tomorrow -0800", fmt="") == datetime(2000, 1, 6, 0, 0, 0)


@pytest.mark.django_db(transaction=True)
def test_unresolved_comment_warn(
    user,
    phabdouble,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
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

    result = legacy_api_transplants.dryrun(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
    )

    assert not result[
        "warnings"
    ], "warnings should be empty for a revision without unresolved comments"

    phabdouble.transaction(
        transaction_type="inline",
        object=r1,
        comments=["this is not done"],
        fields={"isDone": False},
    )

    result = legacy_api_transplants.dryrun(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
    )

    assert result[
        "warnings"
    ], "warnings should not be empty for a revision with unresolved comments"
    assert (
        result["warnings"][0]["display"] == "Revision has unresolved comments."
    ), "the warning display should match warning_unresolved_comments"


@pytest.mark.django_db(transaction=True)
def test_unresolved_comment_stack(
    user,
    phabdouble,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
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

    result = legacy_api_transplants.dryrun(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
                {"revision_id": "D{}".format(r3["id"]), "diff_id": d3["id"]},
            ]
        },
    )

    assert result[
        "warnings"
    ], "warnings should not be empty for a stack with unresolved comments"
    assert (
        result["warnings"][0]["display"] == "Revision has unresolved comments."
    ), "the warning display should match warning_unresolved_comments"


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
    phabdouble, status, create_state
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
def test_check_author_planned_changes_changes_planned(phabdouble, create_state):
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
    status,
    phabdouble,
    mocked_repo_config,
    create_state,
    release_management_project,
    needs_data_classification_project,
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
    phabdouble,
    mocked_repo_config,
    create_state,
    release_management_project,
    needs_data_classification_project,
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
    phabdouble, create_state, needs_data_classification_project
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    "superuser,user_perms,group_perms,should_allow",
    (
        (False, [], [], False),
        (False, [], ["scm_level_3"], False),
        (False, ["scm_level_3"], [], True),
        (True, [], [], False),
        (True, [], ["scm_level_3"], False),
        (True, ["scm_level_3"], [], True),
    ),
)
def test_blocker_scm_permission(
    phabdouble: PhabricatorDouble,
    create_state: Callable,
    scm_user: Callable,
    make_superuser: Callable,
    user_perms: list[str],
    group_perms: list[str],
    superuser: bool,
    should_allow: bool,
):
    repo = phabdouble.repo()
    # Create a revision/diff pair without NSPR or NSS changes.
    revision = phabdouble.revision(repo=repo)
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff_normal = phabdouble.diff(revision=revision)

    user = scm_user(
        [Permission.objects.get(codename=perm) for perm in user_perms],
        "password",
        [Permission.objects.get(codename=perm) for perm in group_perms],
    )

    if superuser:
        user = make_superuser(user)

    mock_landing_assessment = mock.MagicMock()
    mock_landing_assessment.lando_user = user

    stack_state = create_state(phab_revision, mock_landing_assessment)

    blocker = blocker_user_scm_level(
        revision=phab_revision, diff=diff_normal, stack_state=stack_state
    )

    if should_allow:
        assert blocker is None, "User with direct required SCM level should be allowed"
    else:
        assert blocker == (
            "You have insufficient permissions to land or your access has expired. "
            "main.scm_level_3 is required. See the FAQ for help."
        ), "User without direct required SCM level should be rejected"


@pytest.mark.django_db
def test_blocker_nsprnss_files(phabdouble, create_state, get_failing_check_diff):
    repo = phabdouble.repo()

    # Create a revision/diff pair without NSPR or NSS changes.
    revision = phabdouble.revision(repo=repo)
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff_normal = phabdouble.diff(revision=revision)

    # Create a revision/diff pair with an NSPR change, and commit message allowing it.
    revision_nspr_allowed = phabdouble.revision(
        repo=repo, depends_on=[revision], title="UPGRADE_NSPR_RELEASE"
    )
    phab_revision_nspr_allowed = phabdouble.api_object_for(
        revision_nspr_allowed,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff_nspr_allowed = phabdouble.diff(
        rawdiff=get_failing_check_diff("nspr"), revision=revision_nspr_allowed
    )

    # Create a revision/diff pair with an NSS change, and commit message allowing it.
    revision_nss_allowed = phabdouble.revision(
        repo=repo, depends_on=[revision_nspr_allowed], title="UPGRADE_NSS_RELEASE"
    )
    phab_revision_nss_allowed = phabdouble.api_object_for(
        revision_nss_allowed,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff_nss_allowed = phabdouble.diff(
        rawdiff=get_failing_check_diff("nss"), revision=revision_nss_allowed
    )

    # Create a revision/diff pair with an NSPR change.
    revision_nspr = phabdouble.revision(repo=repo, depends_on=[revision_nss_allowed])
    phab_revision_nspr = phabdouble.api_object_for(
        revision_nspr,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff_nspr = phabdouble.diff(
        rawdiff=get_failing_check_diff("nspr"), revision=revision_nspr
    )

    # Create a revision/diff pair with an NSS change.
    revision_nss = phabdouble.revision(repo=repo, depends_on=[revision_nspr])
    phab_revision_nss = phabdouble.api_object_for(
        revision_nss,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff_nss = phabdouble.diff(
        rawdiff=get_failing_check_diff("nss"), revision=revision_nss
    )

    stack_state = create_state(phab_revision_nss)

    assert (
        blocker_prevent_nsprnss_files(
            revision=phab_revision, diff=diff_normal, stack_state=stack_state
        )
        is None
    ), "Diff without NSS or NSPR changes should pass the check."

    assert (
        blocker_prevent_nsprnss_files(
            revision=phab_revision_nspr_allowed,
            diff=diff_nspr_allowed,
            stack_state=stack_state,
        )
        is None
    ), "Diff with explicit NSPR changes should pass the check."

    assert (
        blocker_prevent_nsprnss_files(
            revision=phab_revision_nss_allowed,
            diff=diff_nss_allowed,
            stack_state=stack_state,
        )
        is None
    ), "Diff with explicit NSS changes should pass the check."

    assert (
        blocker_prevent_nsprnss_files(
            revision=phab_revision_nspr,
            diff=diff_nspr,
            stack_state=stack_state,
        )
        == "Revision makes changes to restricted directories: vendored NSPR directories: `nsprpub/.keep`."
    ), "Diff with NSPR changes should fail the check."

    assert (
        blocker_prevent_nsprnss_files(
            revision=phab_revision_nss,
            diff=diff_nss,
            stack_state=stack_state,
        )
        == "Revision makes changes to restricted directories: vendored NSS directories: `security/nss/.keep`."
    ), "Diff with NSS changes should fail the check."


@pytest.mark.django_db
def test_blocker_prevent_submodules(phabdouble, create_state, get_failing_check_diff):
    repo = phabdouble.repo()

    # Create a revision/diff pair without a submodule.
    revision = phabdouble.revision(repo=repo)
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff_normal = phabdouble.diff(revision=revision)

    # Create a revision/diff pair with a submodule.
    revision_submodule = phabdouble.revision(repo=repo, depends_on=[revision])
    phab_revision_submodule = phabdouble.api_object_for(
        revision_submodule,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff_submodule = phabdouble.diff(
        rawdiff=get_failing_check_diff("submodule"), revision=revision_submodule
    )

    stack_state = create_state(phab_revision_submodule)

    assert (
        blocker_prevent_submodules(
            revision=phab_revision, diff=diff_normal, stack_state=stack_state
        )
        is None
    ), "Diff without submodules present should pass the check."

    assert (
        blocker_prevent_submodules(
            revision=phab_revision_submodule,
            diff=diff_submodule,
            stack_state=stack_state,
        )
        == "Revision introduces a Git submodule into the repository."
    ), "Diff with submodules present should fail the check."


@pytest.mark.django_db
def test_blocker_prevent_symlinks(phabdouble, create_state, get_failing_check_diff):
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
    diff_symlink = phabdouble.diff(
        rawdiff=get_failing_check_diff("symlink"), revision=revision_symlink
    )

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


@pytest.mark.django_db
def test_blocker_try_task_config_no_landing_state(
    phabdouble, mocked_repo_config, create_state, get_failing_check_diff
):
    repo = phabdouble.repo()

    revision = phabdouble.revision(repo=repo)
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff = phabdouble.diff(
        revision=revision, rawdiff=get_failing_check_diff("try_task_config")
    )

    stack_state = create_state(phab_revision)

    assert (
        blocker_try_task_config(
            revision=phab_revision, diff=diff, stack_state=stack_state
        )
        == "Revision introduces the `try_task_config.json` file."
    ), "`try_task_config.json` should be rejected."


@pytest.mark.django_db
def test_blocker_try_task_config_landing_state_non_try(
    phabdouble, mocked_repo_config, create_state, get_failing_check_diff
):
    repo = phabdouble.repo()

    revision = phabdouble.revision(repo=repo)
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    diff = phabdouble.diff(
        revision=revision, rawdiff=get_failing_check_diff("try_task_config")
    )

    stack_state = create_state(phab_revision)

    assert (
        blocker_try_task_config(
            revision=phab_revision, diff=diff, stack_state=stack_state
        )
        == "Revision introduces the `try_task_config.json` file."
    ), "`try_task_config.json` should be rejected."


@pytest.mark.django_db
def test_warning_multiple_authors(phabdouble, mocked_repo_config, create_state):
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
    app,
    user,
    phabdouble,
    treestatusdouble,
    register_codefreeze_uri,
    mocked_repo_config,
    repo_mc,
    needs_data_classification_project,
):
    new_repo = repo_mc(SCM_TYPE_GIT)
    new_repo.legacy_source = Repo.objects.get(name="mozilla-central")
    new_repo.save()
    phabrepo = phabdouble.repo(name="mozilla-central")
    reviewer = phabdouble.user(username="reviewer")

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabrepo)
    phabdouble.reviewer(r1, reviewer)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabrepo, depends_on=[r1])
    phabdouble.reviewer(r2, reviewer)

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabrepo, depends_on=[r2])

    phabdouble.reviewer(r3, reviewer)

    result, status_code = legacy_api_transplants.post(
        phabdouble.get_phabricator_client(),
        user,
        {
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
                {"revision_id": "D{}".format(r3["id"]), "diff_id": d3["id"]},
            ]
        },
    )
    assert status_code == 202
    assert "id" in result
    job_id = result["id"]

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
    assert job.status == JobStatus.SUBMITTED
    assert job.target_repo == new_repo
    assert job.landed_phabricator_revisions == {1: 1, 2: 2, 3: 3}
