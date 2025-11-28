"""Helpers for building uplift-related template context."""

from dataclasses import dataclass
from typing import Self, Sequence

from django.core.handlers.wsgi import WSGIRequest
from django.db.models import Prefetch, QuerySet

from lando.api.legacy.stacks import RevisionStack
from lando.api.legacy.validation import revision_id_to_int
from lando.main.models import Repo
from lando.main.models.uplift import UpliftJob, UpliftRevision, UpliftSubmission
from lando.ui.legacy.forms import (
    LinkUpliftAssessmentForm,
    UpliftAssessmentForm,
    UpliftRequestForm,
)


@dataclass(frozen=True, slots=True)
class UpliftContext:
    """Container for uplift values supplied to stack templates."""

    requests: Sequence[UpliftSubmission]
    request_form: UpliftRequestForm
    assessment_form: UpliftAssessmentForm | None
    has_assessment: bool
    assessment_link_form: LinkUpliftAssessmentForm | None
    can_create_uplift_submission: bool
    revision_id: int

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
        source_revisions = [
            revision_id_to_int(revisions[revision_phid]["id"])
            for revision_phid in stack.iter_stack_from_root(dest=revision_phid)
        ]
        request_form = UpliftRequestForm(initial={"source_revisions": source_revisions})

        # Look for an existing `UpliftRevision` for this revision.
        uplift_revision = UpliftRevision.one_or_none(revision_id=revision_id)

        uplift_requests = uplift_context_for_revision(revision_id)

        has_assessment = bool(uplift_revision and uplift_revision.assessment_id)

        assessment_form = None
        assessment_link_form = None

        if cls.can_request_uplift(request, revision_repo):
            assessment_form = cls.build_assessment_form(uplift_revision)
            assessment_link_form = LinkUpliftAssessmentForm(user=request.user)

        return cls(
            requests=tuple(uplift_requests),
            request_form=request_form,
            assessment_form=assessment_form,
            has_assessment=has_assessment,
            assessment_link_form=assessment_link_form,
            can_create_uplift_submission=cls.can_create_submission(request),
            revision_id=revision_id,
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
    def build_assessment_form(
        uplift_revision: UpliftRevision | None,
    ) -> UpliftAssessmentForm:
        """Return the edit form for the supplied uplift revision."""
        if uplift_revision and uplift_revision.assessment:
            return UpliftAssessmentForm(instance=uplift_revision.assessment)

        return UpliftAssessmentForm()

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
