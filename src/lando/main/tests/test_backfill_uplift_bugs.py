from io import StringIO

import pytest
from django.core.management import call_command

from lando.conftest import UPLIFT_ASSESSMENT_ANSWERS
from lando.main.models.uplift import UpliftAssessment, UpliftRevision

BUG_ID = 987654


def run_backfill(**options) -> str:
    """Run the backfill command, returning what it wrote to stdout."""
    out = StringIO()
    call_command("backfill_uplift_bugs", stdout=out, **options)
    return out.getvalue()


@pytest.mark.django_db
def test_backfill_resolves_the_bug_from_a_linked_revision(user, phabdouble):
    """An assessment with no bug takes it from the revision it is linked to."""
    phabdouble.user(api_key=user.profile.phabricator_api_key)
    revision_id = phabdouble.revision(bug_id=BUG_ID)["id"]

    assessment = UpliftAssessment.objects.create(
        user=user, bug_id=None, **UPLIFT_ASSESSMENT_ANSWERS
    )
    UpliftRevision.link_revision_to_assessment(revision_id, assessment)

    run_backfill(execute=True)

    assessment.refresh_from_db()
    assert assessment.bug_id == BUG_ID, (
        "The bug should be taken from the linked revision."
    )


@pytest.mark.django_db
def test_backfill_is_a_dry_run_without_execute(user, phabdouble):
    """Nothing is written unless `--execute` is passed."""
    phabdouble.user(api_key=user.profile.phabricator_api_key)
    revision_id = phabdouble.revision(bug_id=BUG_ID)["id"]

    assessment = UpliftAssessment.objects.create(
        user=user, bug_id=None, **UPLIFT_ASSESSMENT_ANSWERS
    )
    UpliftRevision.link_revision_to_assessment(revision_id, assessment)

    output = run_backfill()

    assessment.refresh_from_db()
    assert assessment.bug_id is None, "A dry run should not write the bug number."
    assert "[DRY RUN]" in output, "A dry run should report what it would have done."
    assert str(BUG_ID) in output, "A dry run should report the bug it resolved."


@pytest.mark.django_db
def test_backfill_skips_assessments_it_cannot_resolve(user, phabdouble):
    """An assessment reaching no revision, or no bug, is reported and left alone."""
    phabdouble.user(api_key=user.profile.phabricator_api_key)

    unreachable = UpliftAssessment.objects.create(
        user=user, bug_id=None, **UPLIFT_ASSESSMENT_ANSWERS
    )

    # A revision that exists but carries no bug number.
    bugless_revision_id = phabdouble.revision()["id"]
    bugless = UpliftAssessment.objects.create(
        user=user, bug_id=None, **UPLIFT_ASSESSMENT_ANSWERS
    )
    UpliftRevision.link_revision_to_assessment(bugless_revision_id, bugless)

    output = run_backfill(execute=True)

    unreachable.refresh_from_db()
    bugless.refresh_from_db()

    assert unreachable.bug_id is None, (
        "An assessment with no revision should be left alone."
    )
    assert bugless.bug_id is None, (
        "An assessment whose revision has no bug should be left alone."
    )
    assert "no revision to resolve a bug from" in output, (
        "The unreachable assessment should be reported."
    )
    assert "has no bug number" in output, (
        "The assessment whose revision has no bug should be reported."
    )


@pytest.mark.django_db
def test_backfill_leaves_assessments_that_already_have_a_bug(user, phabdouble):
    """Assessments with a bug are not revisited."""
    phabdouble.user(api_key=user.profile.phabricator_api_key)

    assessment = UpliftAssessment.objects.create(
        user=user, bug_id=BUG_ID, **UPLIFT_ASSESSMENT_ANSWERS
    )

    output = run_backfill(execute=True)

    assessment.refresh_from_db()
    assert assessment.bug_id == BUG_ID, "An existing bug number should be untouched."
    assert "Found 0 assessments" in output, (
        "Assessments that already have a bug should not be considered."
    )
