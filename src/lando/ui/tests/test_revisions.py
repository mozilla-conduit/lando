from typing import Callable
from unittest import mock

import pytest
from django.http.response import Http404

from lando.api.legacy.projects import NEEDS_DATA_CLASSIFICATION_SLUG
from lando.api.tests.mocks import PhabricatorDouble
from lando.main.models import (
    JobStatus,
)
from lando.main.scm import SCMType
from lando.ui.legacy.revisions import RevisionView


@pytest.fixture
def mock_phabricator_user_request() -> mock.Mock:
    mock_request = mock.Mock()
    mock_request.user = mock.Mock()
    mock_request.user.is_authenticated = True
    mock_request.user.profile = mock.Mock()
    mock_request.user.profile.phabricator_api_key = "api-mock-phabricator-key"

    return mock_request


@pytest.mark.django_db(transaction=True)
def test_RevisionView_get_unauthorised_or_missing(
    mock_phabricator_user_request: mock.Mock,
    phabdouble: PhabricatorDouble,
    repo_mc: Callable,
    make_landing_job: Callable,
):
    phabdouble.project(NEEDS_DATA_CLASSIFICATION_SLUG)
    phab_repo = phabdouble.repo()
    repo = repo_mc(SCMType.GIT, name=phab_repo["name"])

    # Create a transplant pointing at a revision that will not
    # be returned by phabricator.
    make_landing_job(
        target_repo=repo,
        landing_path=[(1, 1)],
        status=JobStatus.SUBMITTED,
    )

    mock_phabricator_user_request.user.is_authenticated = False
    mock_phabricator_user_request.user.profile.phabricator_api_key = None

    with pytest.raises(Http404):
        RevisionView().get(mock_phabricator_user_request, revision_id=1)


@mock.patch("lando.ui.legacy.revisions.TemplateResponse")
@pytest.mark.django_db(transaction=True)
def test_RevisionView_get_for_entire_stack(
    mock_template_response: mock.Mock,
    phabdouble: PhabricatorDouble,
    make_landing_job: Callable,
    repo_mc: Callable,
    mock_phabricator_user_request: mock.Mock,
):

    phabdouble.project(NEEDS_DATA_CLASSIFICATION_SLUG)
    phab_repo = phabdouble.repo()
    repo_mc(SCMType.GIT, name=phab_repo["name"])

    d1a = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1a, repo=phab_repo)
    d1b = phabdouble.diff(revision=r1)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phab_repo, depends_on=[r1])

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phab_repo, depends_on=[r1])

    d_not_in_stack = phabdouble.diff()
    r_not_in_stack = phabdouble.revision(diff=d_not_in_stack, repo=phabdouble.repo())

    repo = repo_mc(SCMType.GIT)

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

    RevisionView().get(mock_phabricator_user_request, revision_id=r2["id"])

    mock_template_response.assert_called_once()

    jobs = mock_template_response.call_args[1].get("context").get("landing_jobs")

    assert len(jobs) == 4

    tmap = {i.id: i for i in jobs}
    assert t_not_in_stack.id not in tmap
    assert all(t.id in tmap for t in (t1, t2, t3, t4))


@mock.patch("lando.ui.legacy.revisions.TemplateResponse")
@pytest.mark.django_db(transaction=True)
def test_RevisionView_get_from_middle_revision(
    mock_template_response: mock.Mock,
    mock_phabricator_user_request: mock.Mock,
    phabdouble: PhabricatorDouble,
    repo_mc: Callable,
    make_landing_job: Callable,
):
    phabdouble.project(NEEDS_DATA_CLASSIFICATION_SLUG)
    phab_repo = phabdouble.repo()
    repo_mc(SCMType.GIT, name=phab_repo["name"])

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phab_repo)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phab_repo, depends_on=[r1])

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phab_repo, depends_on=[r1])

    t = make_landing_job(
        landing_path=[(r1["id"], d1["id"]), (r2["id"], d2["id"]), (r3["id"], d3["id"])],
        status=JobStatus.FAILED,
    )

    RevisionView().get(mock_phabricator_user_request, revision_id=r2["id"])

    mock_template_response.assert_called_once()

    jobs = mock_template_response.call_args[1].get("context").get("landing_jobs")

    assert len(jobs) == 1
    assert jobs[0].id == t.id
