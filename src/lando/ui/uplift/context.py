"""Helpers for building uplift-related template context."""

import logging
from dataclasses import dataclass
from typing import Self, Sequence

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest

from lando.api.legacy.stacks import RevisionStack
from lando.api.legacy.validation import revision_id_to_int
from lando.main.models.uplift import (
    UpliftAssessment,
    UpliftJob,
    UpliftRevision,
)
from lando.ui.legacy.forms import (
    UpliftAssessmentForm,
    UpliftRequestForm,
)
from lando.utils.const import UPLIFT_DOCS_URL

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UpliftAssessmentCard:
    """One of the bug's uplift assessments, as shown on the revision page."""

    # The assessment being displayed.
    assessment: UpliftAssessment

    # Edit form pre-filled with this assessment's answers.
    form: UpliftAssessmentForm

    # Whether this is the assessment linked to the revision being viewed.
    is_linked: bool

    # Phabricator revision IDs already carrying this assessment.
    revision_ids: Sequence[int]

    # Every uplift job queued from this assessment, one per target train.
    jobs: Sequence[UpliftJob]


@dataclass(frozen=True, slots=True)
class UpliftContext:
    """Container for uplift values supplied to stack templates."""

    request_form: UpliftRequestForm
    can_create_uplift_submission: bool
    revision_id: int

    # Bug the current revision references, or `None` when it has none.
    bug_id: int | None

    # Every assessment recorded against `bug_id`, including those authored by
    # other users and those linked to revisions elsewhere in the bug.
    bug_assessments: Sequence[UpliftAssessmentCard]

    # Empty form for authoring a new assessment on the bug. `None` when the
    # user may not submit assessments for this revision.
    new_assessment_form: UpliftAssessmentForm | None

    docs_url: str
    train_api_url: str

    @classmethod
    def build(
        cls,
        *,
        request: WSGIRequest,
        revision_id: int,
        revision_phid: str,
        revisions: dict[str, dict],
        stack: RevisionStack,
    ) -> Self:
        """Return a populated `UpliftContext` for the given stack view."""
        try:
            source_revisions = [
                revision_id_to_int(revisions[revision_phid]["id"])
                for revision_phid in stack.iter_stack_from_root(dest=revision_phid)
            ]
        except ValueError:
            logger.exception(
                "Could not walk stack to revision %s, using single revision fallback.",
                revision_phid,
            )

            # Fall back to just the current revision if we can't walk the stack.
            source_revisions = [revision_id]

        request_form = UpliftRequestForm(initial={"source_revisions": source_revisions})

        # Look for an existing `UpliftRevision` for this revision.
        uplift_revision = UpliftRevision.one_or_none(revision_id=revision_id)

        # The assessment currently attached to this revision, if any. Its card
        # is the one marked as linked.
        linked_assessment = uplift_revision.assessment if uplift_revision else None

        bug_id = revisions[revision_phid].get("bug_id")

        new_assessment_form = None

        if cls.can_author_assessment(request, bug_id):
            new_assessment_form = UpliftAssessmentForm()

        return cls(
            request_form=request_form,
            can_create_uplift_submission=cls.can_create_submission(request),
            revision_id=revision_id,
            bug_id=bug_id,
            bug_assessments=cls.build_assessment_cards(bug_id, linked_assessment),
            new_assessment_form=new_assessment_form,
            docs_url=UPLIFT_DOCS_URL,
            train_api_url=settings.WHATTRAINISITNOW_UPLIFT_TRAIN_API_URL,
        )

    @staticmethod
    def can_author_assessment(request: WSGIRequest, bug_id: int | None) -> bool:
        """Return `True` if the user should see the uplift assessment forms.

        Deliberately not gated on `approval_required`: that marks a repo as an
        uplift *target*, so gating on it hides the assessment from the mainline
        revision the uplift was requested from.
        """
        return bool(request.user.is_authenticated and bug_id)

    @classmethod
    def build_assessment_cards(
        cls, bug_id: int | None, linked_assessment: UpliftAssessment | None
    ) -> tuple[UpliftAssessmentCard, ...]:
        """Return a card for each assessment recorded against the bug."""
        assessments = list(UpliftAssessment.for_bug(bug_id))
        jobs_by_assessment = cls.jobs_by_assessment(assessments)

        return tuple(
            UpliftAssessmentCard(
                assessment=assessment,
                form=UpliftAssessmentForm(instance=assessment),
                is_linked=(
                    linked_assessment is not None
                    and linked_assessment.pk == assessment.pk
                ),
                revision_ids=[
                    uplift_revision.revision_id
                    for uplift_revision in assessment.revisions.all()
                    if uplift_revision.revision_id is not None
                ],
                jobs=jobs_by_assessment.get(assessment.pk, []),
            )
            for assessment in assessments
        )

    @staticmethod
    def jobs_by_assessment(
        assessments: Sequence[UpliftAssessment],
    ) -> dict[int, list[UpliftJob]]:
        """Group every uplift job queued from the given assessments, by assessment.

        A submission is just an assessment plus the jobs one request queued, so
        the jobs of all of an assessment's submissions belong on its card
        together.
        """
        jobs = (
            UpliftJob.objects.filter(
                submission__assessment__in=assessments,
            )
            .select_related("target_repo", "submission")
            .order_by("id")
        )

        grouped: dict[int, list[UpliftJob]] = {}
        for job in jobs:
            grouped.setdefault(job.submission.assessment_id, []).append(job)

        return grouped

    @staticmethod
    def can_create_submission(request: WSGIRequest) -> bool:
        """Return `True` when the user can submit uplift jobs."""
        return (
            request.user.is_authenticated and request.user.profile.phabricator_api_key
        )
