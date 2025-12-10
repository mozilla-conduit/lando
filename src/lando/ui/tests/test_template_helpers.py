import re
import urllib.parse

import pytest

from lando.jinja import (
    avatar_url,
    build_manual_uplift_instructions,
    linkify_bug_numbers,
    linkify_faq,
    linkify_phabricator_revision_ids,
    linkify_phabricator_revision_urls,
    linkify_sec_bug_docs,
    linkify_transplant_details,
    phabricator_revision_url,
    repo_branch_url,
    repo_path,
)
from lando.main.models import JobStatus, LandingJob, Repo, SCMType
from lando.main.models.revision import Revision, RevisionLandingJob
from lando.main.models.uplift import UpliftAssessment, UpliftJob, UpliftSubmission


@pytest.mark.parametrize(
    "input_url,output_url",
    [
        (
            "https://lh3.googleusercontent.com/-ABCDef/123/photo.jpg",
            "https://lh3.googleusercontent.com/-ABCDef/123/photo.jpg",
        ),
        (
            "https://s.gravatar.com/avatar/9b665?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Fcs.png",  # noqa
            "https://s.gravatar.com/avatar/9b665?s=480&r=pg&d=identicon",
        ),
        (
            "https://s.gravatar.com/avatar/123b",
            "https://s.gravatar.com/avatar/123b?d=identicon",
        ),
        (
            "//www.gravatar.com/avatar/123b?s=480&r=pg&d=robohash",
            "//www.gravatar.com/avatar/123b?s=480&r=pg&d=identicon",
        ),
        ("/relative_path_only", ""),
        ("1 invalid url", ""),
        (9000, ""),
    ],
)
def test_avatar_url(input_url, output_url):
    # Query params are not guaranteed to be in the same order, so
    # we cannot do string comparison of the URLs.
    expected = urllib.parse.urlparse(output_url)
    actual = urllib.parse.urlparse(avatar_url(input_url))
    expected_qs = urllib.parse.parse_qs(expected.query)
    actual_qs = urllib.parse.parse_qs(actual.query)

    for argument in expected_qs:
        assert expected_qs[argument] == actual_qs[argument]

    assert (expected.scheme, expected.netloc, expected.path) == (
        actual.scheme,
        actual.netloc,
        actual.path,
    )


@pytest.mark.parametrize(
    "input_text,output_text",
    [
        ("Bug 123", '<a href="http://bmo.test/show_bug.cgi?id=123">Bug 123</a>'),
        ("bug 123", '<a href="http://bmo.test/show_bug.cgi?id=123">bug 123</a>'),
        (
            "Testing Bug 1413384 word boundaries",
            (
                'Testing <a href="http://bmo.test/show_bug.cgi?id=1413384">'
                "Bug 1413384</a> word boundaries"
            ),
        ),
        (
            "Bug 123 - commit title. r=test\n\nCommit message Bug 456",
            (
                '<a href="http://bmo.test/show_bug.cgi?id=123">Bug 123</a> - '
                "commit title. r=test\n\nCommit message "
                '<a href="http://bmo.test/show_bug.cgi?id=456">Bug 456</a>'
            ),
        ),
        ("A message with no bug number", "A message with no bug number"),
    ],
)
def test_linkify_bug_numbers(input_text, output_text):
    assert output_text == linkify_bug_numbers(input_text)


@pytest.mark.parametrize(
    "input_text,output_text",
    [
        (
            "http://phabricator.test/D123",
            ('<a href="http://phabricator.test/D123">http://phabricator.test/D123</a>'),
        ),
        (
            "word http://phabricator.test/D201525 boundaries",
            (
                'word <a href="http://phabricator.test/D201525">'
                "http://phabricator.test/D201525</a> boundaries"
            ),
        ),
        (
            (
                "multiple http://phabricator.test/D123\n"
                "revisions http://phabricator.test/D456"
            ),
            (
                'multiple <a href="http://phabricator.test/D123">'
                "http://phabricator.test/D123</a>\nrevisions "
                '<a href="http://phabricator.test/D456">'
                "http://phabricator.test/D456</a>"
            ),
        ),
        (
            "No revision example: http://phabricator.test/herald/",
            "No revision example: http://phabricator.test/herald/",
        ),
    ],
)
def test_linkify_phabricator_revision_urls(input_text, output_text):
    assert output_text == linkify_phabricator_revision_urls(input_text)


@pytest.mark.parametrize(
    "input_text,output_text",
    [
        ("D1234", '<a href="http://phabricator.test/D1234" target="_blank">D1234</a>'),
        (
            "blah D1234",
            'blah <a href="http://phabricator.test/D1234" target="_blank">D1234</a>',
        ),
        (
            "blah in D1234.",
            'blah in <a href="http://phabricator.test/D1234" '
            'target="_blank">D1234</a>.',
        ),
        (
            "(see D1234).",
            '(see <a href="http://phabricator.test/D1234" target="_blank">D1234</a>).',
        ),
        (
            "(see D1234, D12345).",
            '(see <a href="http://phabricator.test/D1234" target="_blank">D1234</a>, '
            '<a href="http://phabricator.test/D12345" target="_blank">D12345</a>).',
        ),
    ],
)
def test_linkify_phabricator_revision_ids(input_text, output_text):
    assert output_text == linkify_phabricator_revision_ids(input_text)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "commit_id, repo_type, repo_url, result",
    [
        (
            "badc0ffe",
            SCMType.GIT,
            "https://github.com/bad/coffee",
            "https://github.com/bad/coffee/commit/badc0ffe",
        ),
        (
            "badc0ffe",
            SCMType.GIT,
            "https://github.com/bad/coffee.git",
            "https://github.com/bad/coffee/commit/badc0ffe",
        ),
        (
            "badc0ffe",
            SCMType.HG,
            "https://hg.mozilla.org/bad/coffee",
            "https://hg.mozilla.org/bad/coffee/rev/badc0ffe",
        ),
    ],
)
def test_linkify_transplant_details(
    repo_mc, commit_id: str, repo_type: str, repo_url: str, result: str
):
    repo = repo_mc(repo_type)
    repo.url = repo_url
    landing_job = LandingJob(
        landed_commit_id=commit_id, status=JobStatus.LANDED, target_repo=repo
    )
    re_string = re.compile(r'.*href="(.*)".*')
    out = linkify_transplant_details(f"{commit_id} is here", landing_job)
    url = re_string.match(out).groups()[0]
    assert url == result


@pytest.mark.parametrize(
    "input_text,output_text",
    [
        ("faq", '<a href="https://wiki.mozilla.org/Phabricator/FAQ#Lando">faq</a>'),
        ("FAQ", '<a href="https://wiki.mozilla.org/Phabricator/FAQ#Lando">FAQ</a>'),
        (
            "faqual message that should not be linked",
            "faqual message that should not be linked",
        ),
    ],
)
def test_linkify_faq(input_text, output_text):
    assert output_text == linkify_faq(input_text)


@pytest.mark.parametrize(
    "input_text,output_text",
    [
        (
            "security bug approval process",
            '<a href="https://firefox-source-docs.mozilla.org/bug-mgmt/processes/security-approval.html">security bug approval process</a>',  # noqa
        ),
        (
            "Security Bug Approval Process",
            '<a href="https://firefox-source-docs.mozilla.org/bug-mgmt/processes/security-approval.html">Security Bug Approval Process</a>',  # noqa
        ),
        (
            "security bug processes being used in a normal sentence",
            "security bug processes being used in a normal sentence",
        ),
    ],
)
def test_linkify_sec_bug_docs(input_text, output_text):
    assert output_text == linkify_sec_bug_docs(input_text)


@pytest.mark.parametrize(
    "repo_url,path",
    [
        (
            "https://hg.mozilla.org/automation/phabricator-qa-stage",
            "automation/phabricator-qa-stage",
        ),
        ("https://hg.mozilla.org/comm-central/", "comm-central"),
        ("http://hg.test", "http://hg.test"),
        (None, ""),
    ],
)
def test_repo_path(repo_url, path):
    assert path == repo_path(repo_url)


@pytest.mark.parametrize(
    "repo,path",
    [
        (
            Repo(
                scm_type=SCMType.GIT,
                url="http://git.test/test-repo",
                default_branch="testing",
            ),
            "http://git.test/test-repo/log/?h=testing",
        ),
        (
            Repo(
                scm_type=SCMType.GIT,
                url="https://github.com/mozilla-conduit/test-repo",
                default_branch="testing",
            ),
            "https://github.com/mozilla-conduit/test-repo/tree/testing",
        ),
        (
            Repo(
                scm_type=SCMType.HG,
                url="https://example.com/test",
                default_branch="testing",
            ),
            "https://example.com/test",
        ),
    ],
)
def test_repo_branch_url(repo, path):
    assert path == repo_branch_url(repo)


def test_revision_url__integer():
    revision_id = 1234
    expected_result = "http://phabricator.test/D1234"
    actual_result = phabricator_revision_url(revision_id)
    assert expected_result == actual_result


def test_revision_url__prepended_string():
    revision_id = "D1234"
    expected_result = "http://phabricator.test/D1234"
    actual_result = phabricator_revision_url(revision_id)
    assert expected_result == actual_result


def test_revision_url__string():
    revision_id = "1234"
    expected_result = "http://phabricator.test/D1234"
    actual_result = phabricator_revision_url(revision_id)
    assert expected_result == actual_result


def test_revision_url__general_case_with_diff():
    revision_id = 123
    diff_id = 456
    expected_result = "http://phabricator.test/D123?id=456"
    actual_result = phabricator_revision_url(revision_id, diff_id)
    assert expected_result == actual_result


@pytest.mark.django_db
def test_build_manual_uplift_instructions(user):
    """Test manual uplift instructions with complete data."""
    # Create repo with all expected fields set.
    repo = Repo.objects.create(
        name="firefox-beta",
        short_name="beta",
        default_branch="beta",
        url="https://github.com/mozilla/gecko-dev",
        scm_type=SCMType.GIT,
    )

    # Create revisions.
    rev1 = Revision.objects.create(revision_id=123)
    rev2 = Revision.objects.create(revision_id=124)
    rev3 = Revision.objects.create(revision_id=125)

    # Create RevisionLandingJob records with commit IDs.
    RevisionLandingJob.objects.create(revision=rev1, commit_id="abc123def456")
    RevisionLandingJob.objects.create(revision=rev2, commit_id="def789ghi012")
    RevisionLandingJob.objects.create(revision=rev3, commit_id="ghi345jkl678")

    # Create assessment and submission.
    assessment = UpliftAssessment.objects.create(
        user=user,
        user_impact="Test impact",
        risk_level_explanation="Low risk",
        string_changes="None",
    )
    submission = UpliftSubmission.objects.create(
        requested_by=user,
        assessment=assessment,
        requested_revision_ids=[123, 124, 125],
    )

    # Create job and link revisions.
    job = UpliftJob.objects.create(
        target_repo=repo, status=JobStatus.FAILED, submission=submission
    )
    job.add_revisions([rev1, rev2, rev3])
    job.sort_revisions([rev1, rev2, rev3])

    result = build_manual_uplift_instructions(job)

    expected = (
        "git fetch origin\n"
        "git switch -c uplift-beta-D123 origin/beta\n"
        "git cherry-pick abc123def456\n"
        "git cherry-pick def789ghi012\n"
        "git cherry-pick ghi345jkl678\n"
        f"moz-phab uplift --train beta --assessment-id {assessment.id}"
    )

    assert result == expected, "Generated commands should match expected."
