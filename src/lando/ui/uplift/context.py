"""Helpers for building uplift-related template context."""

import logging
from dataclasses import dataclass
from typing import Self, Sequence

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import Prefetch, QuerySet

from lando.api.legacy.stacks import RevisionStack
from lando.api.legacy.validation import revision_id_to_int
from lando.main.models import Repo
from lando.main.models.uplift import (
    UpliftAssessment,
    UpliftJob,
    UpliftRevision,
    UpliftSubmission,
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


@dataclass(frozen=True, slots=True)
class UpliftContext:
    """Container for uplift values supplied to stack templates."""

    requests: Sequence[UpliftSubmission]
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
        revision_repo: Repo | None,
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

        uplift_requests = uplift_context_for_revision(revision_id)

        # The assessment currently attached to this revision, if any. Its card
        # is the one marked as linked.
        linked_assessment = uplift_revision.assessment if uplift_revision else None

        bug_id = revisions[revision_phid].get("bug_id")

        new_assessment_form = None

        if cls.can_request_uplift(request, revision_repo):
            new_assessment_form = UpliftAssessmentForm()

        return cls(
            requests=tuple(uplift_requests),
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
    def can_request_uplift(request: WSGIRequest, revision_repo: Repo | None) -> bool:
        """Return `True` if the user should see uplift assessment forms."""
        return (
            request.user.is_authenticated
            and revision_repo
            and revision_repo.approval_required
        )

    @staticmethod
    def build_assessment_cards(
        bug_id: int | None, linked_assessment: UpliftAssessment | None
    ) -> tuple[UpliftAssessmentCard, ...]:
        """Return a card for each assessment recorded against the bug."""
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
            )
            for assessment in UpliftAssessment.for_bug(bug_id)
        )

    @staticmethod
    def can_create_submission(request: WSGIRequest) -> bool:
        """Return `True` when the user can submit uplift jobs."""
        return (
            request.user.is_authenticated and request.user.profile.phabricator_api_key
        )


def uplift_context_for_revision(revision_id: int) -> QuerySet:
    """Return all UpliftSubmission objects relevant to this revision.

    Relevant if:
      - this revision was originally requested (in requested_revision_ids)
      - this revision was created by an uplift job (UpliftJob.created_revision_ids).
    """
    base_qs = (
        UpliftSubmission.objects.select_related("assessment", "requested_by")
        .prefetch_related(
            Prefetch(
                "uplift_jobs",
                queryset=UpliftJob.objects.select_related("target_repo").order_by("id"),
            )
        )
        .order_by("-created_at")
    )

    # Original side: the revision was requested (e.g. D123 in requested_revision_ids).
    original_qs = base_qs.filter(requested_revision_ids__contains=[revision_id])

    # Uplifted side: the revision was produced by an uplift job.
    uplifted_qs = base_qs.filter(
        uplift_jobs__created_revision_ids__contains=[revision_id]
    )

    return (original_qs | uplifted_qs).distinct()
