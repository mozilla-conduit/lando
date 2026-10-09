"""Helpers for building uplift-related template context."""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Self, Sequence

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import Prefetch

from lando.api.legacy.projects import RELMAN_PROJECT_SLUG, get_project_phid
from lando.api.legacy.stacks import (
    RevisionStack,
    get_diffs_by_phid,
    get_revisions_by_id,
)
from lando.api.legacy.validation import revision_id_to_int
from lando.main.models import JobStatus, Repo
from lando.main.models.uplift import (
    UpliftAssessment,
    UpliftJob,
    UpliftRevision,
)
from lando.main.support import diff_has_disallowed_author
from lando.ui.legacy.forms import (
    UpliftAssessmentForm,
    UpliftRequestForm,
)
from lando.utils.const import UPLIFT_DOCS_URL
from lando.utils.phabricator import PhabricatorAPIException, PhabricatorClient

logger = logging.getLogger(__name__)


class UpliftTrainOutcome(Enum):
    """What became of one stack carrying an assessment, as its card shows it."""

    CREATED_BY_LANDO = ("Created by Lando", "positive", "fa-check")
    MERGE_CONFLICT = ("Merge conflict", "negative", "fa-times")
    FAILED = ("Failed", "negative", "fa-exclamation-triangle")
    IN_PROGRESS = ("In progress", "warning", "fa-clock-o")
    QUEUED = ("Queued", "", "fa-hourglass-start")
    CANCELLED = ("Cancelled", "", "fa-ban")
    CONFLICT_RESOLVED_BY_HACKBOT = (
        "Conflict resolved by hackbot",
        "positive",
        "fa-check",
    )
    SUBMITTED_WITH_MOZ_PHAB = ("Submitted with moz-phab", "neutral", "fa-terminal")
    SUBMITTED_OUTSIDE_LANDO = (
        "Submitted outside Lando",
        "neutral",
        "fa-question-circle",
    )

    def __init__(self, label: str, badge: str, icon: str):
        # The outcome's label, its Lando `Badge` modifier and its Font Awesome icon.
        self.label = label
        self.badge_class = f"Badge Badge--{badge}" if badge else "Badge"
        self.icon = icon

    @classmethod
    def for_job(cls, job: UpliftJob) -> Self:
        """Return the outcome of the stack `job` was queued to create."""
        if job.status == JobStatus.LANDED:
            return cls.CREATED_BY_LANDO
        if job.status == JobStatus.FAILED:
            # Only a merge conflict fills in the breakdown of failed paths.
            return cls.MERGE_CONFLICT if job.error_breakdown else cls.FAILED
        if job.status == JobStatus.IN_PROGRESS:
            return cls.IN_PROGRESS
        if job.status in (JobStatus.CANCELLED, JobStatus.ABORTED):
            return cls.CANCELLED
        return cls.QUEUED


@dataclass(frozen=True, slots=True)
class UpliftTrainRow:
    """One stack carrying an assessment, as a row of its card's train table."""

    # Name of the train the stack targets, or `None` when it is not known.
    train: str | None

    # Phabricator ID of the stack's tip, or `None` when a job created nothing.
    tip_revision_id: int | None

    # What became of the stack.
    outcome: UpliftTrainOutcome

    # The Lando job behind the stack, or `None` for one made outside Lando.
    job: UpliftJob | None = None


@dataclass(frozen=True, slots=True)
class UpliftTrainGroup:
    """Every stack carrying an assessment for one train."""

    # Name of the train, or `None` for stacks whose train is not known.
    train: str | None

    # The train's stacks: its jobs first, then those made outside Lando.
    rows: Sequence[UpliftTrainRow]


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

    # Phabricator revision IDs an uplift was requested for.
    requested_revision_ids: Sequence[int]

    # The stacks carrying this assessment, grouped by train in the order the
    # trains first appear.
    train_groups: Sequence[UpliftTrainGroup]


@dataclass(frozen=True, slots=True)
class UpliftContext:
    """Container for uplift values supplied to stack templates."""

    request_form: UpliftRequestForm
    can_create_uplift_submission: bool
    revision_id: int

    # Bug the current revision references, or `None` when it has none.
    bug_id: int | None

    # Whether the revision is in an uplift target repo, rather than being the
    # mainline revision an uplift is requested from.
    is_uplift_revision: bool

    # The release-managers group's review status on this uplift revision, ie
    # `accepted`, or `None` while the group is not a reviewer.
    relman_review: str | None

    # Every assessment this revision should display: the bug's, plus any the
    # revision reaches directly, or on a mainline revision only its uplifts.
    bug_assessments: Sequence[UpliftAssessmentCard]

    # Empty form for authoring a new assessment on the bug. `None` when the
    # user may not create, edit or link assessments on this revision.
    new_assessment_form: UpliftAssessmentForm | None

    docs_url: str
    train_api_url: str

    @property
    def linked_card(self) -> UpliftAssessmentCard | None:
        """Return the card of the assessment linked to this revision, if any."""
        return next((card for card in self.bug_assessments if card.is_linked), None)

    @property
    def is_ready_for_review(self) -> bool:
        """Return `True` with a bug and an assessment, and no changes requested."""
        return bool(
            self.bug_id and self.linked_card and self.relman_review != "rejected"
        )

    @property
    def shown_cards(self) -> tuple[UpliftAssessmentCard, ...]:
        """Return the cards shown in full.

        An uplift revision shows only the assessment linked to it; the picker
        lists the rest. A mainline revision shows every uplift requested from it.
        """
        if not self.is_uplift_revision:
            return tuple(self.bug_assessments)

        return (self.linked_card,) if self.linked_card else ()

    @property
    def collapsed_cards(self) -> tuple[UpliftAssessmentCard, ...]:
        """Return the bug's other assessments, folded under the linked one."""
        if not self.is_uplift_revision or self.linked_card is None:
            return ()

        return tuple(card for card in self.bug_assessments if not card.is_linked)

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
        phab: PhabricatorClient | None = None,
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
        is_uplift_revision = bool(revision_repo and revision_repo.approval_required)

        new_assessment_form = None

        if cls.can_author_assessment(request, bug_id, is_uplift_revision):
            new_assessment_form = UpliftAssessmentForm()

        return cls(
            request_form=request_form,
            can_create_uplift_submission=cls.can_create_submission(request),
            revision_id=revision_id,
            bug_id=bug_id,
            is_uplift_revision=is_uplift_revision,
            relman_review=(
                cls.relman_review_status(phab, revisions[revision_phid])
                if is_uplift_revision
                else None
            ),
            bug_assessments=cls.build_assessment_cards(
                bug_id, revision_id, linked_assessment, is_uplift_revision, phab=phab
            ),
            new_assessment_form=new_assessment_form,
            docs_url=UPLIFT_DOCS_URL,
            train_api_url=settings.WHATTRAINISITNOW_UPLIFT_TRAIN_API_URL,
        )

    @staticmethod
    def relman_review_status(
        phab: PhabricatorClient | None, revision: dict
    ) -> str | None:
        """Return the release-managers group's review status on `revision`.

        Phabricator adds the group as a reviewer once the uplift request form is
        set, and landing stays blocked until it accepts. Returns `None` while the
        group is not a reviewer, or when it cannot be looked up.
        """
        if phab is None:
            return None

        try:
            relman_phid = get_project_phid(RELMAN_PROJECT_SLUG, phab)
        except PhabricatorAPIException:
            logger.warning(
                "Could not look up the release-managers group.", exc_info=True
            )
            return None

        return next(
            (
                reviewer["status"]
                for reviewer in revision.get("reviewers", [])
                if reviewer["phid"] == relman_phid
            ),
            None,
        )

    @staticmethod
    def can_author_assessment(
        request: WSGIRequest, bug_id: int | None, is_uplift_revision: bool
    ) -> bool:
        """Return `True` if the user should see the uplift assessment forms.

        A mainline revision is not an uplift, so its assessments come from
        "Request Uplift" rather than being written, edited or linked there.
        """
        return bool(request.user.is_authenticated and bug_id and is_uplift_revision)

    @classmethod
    def build_assessment_cards(
        cls,
        bug_id: int | None,
        revision_id: int,
        linked_assessment: UpliftAssessment | None,
        is_uplift_revision: bool,
        phab: PhabricatorClient | None = None,
    ) -> tuple[UpliftAssessmentCard, ...]:
        """Return a card for each assessment this revision should display.

        `phab` looks up the trains of stacks linked from outside Lando; without
        it their train is shown as unknown.
        """
        assessments = list(
            UpliftAssessment.visible_on_revision(bug_id, revision_id).prefetch_related(
                Prefetch(
                    "uplift_submission__uplift_jobs",
                    queryset=UpliftJob.objects.select_related("target_repo"),
                )
            )
        )

        if not is_uplift_revision:
            logger.debug("Showing only the uplifts requested from D%s.", revision_id)
            assessments = [
                assessment
                for assessment in assessments
                if revision_id in assessment.requested_revision_ids()
            ]

        # A submission is just an assessment plus the jobs one request queued, so
        # the jobs of all of an assessment's submissions belong on its card.
        jobs_by_assessment = {
            assessment.pk: sorted(
                (
                    job
                    for submission in assessment.uplift_submission.all()
                    for job in submission.uplift_jobs.all()
                ),
                key=lambda job: job.id,
            )
            for assessment in assessments
        }

        revision_ids_by_assessment = {
            assessment.pk: [
                uplift_revision.revision_id
                for uplift_revision in assessment.revisions.all()
                if uplift_revision.revision_id is not None
            ]
            for assessment in assessments
        }

        # Revisions a job created are described by that job; the rest were
        # linked from outside Lando, so only Phabricator knows their train.
        outside_ids_by_assessment = {
            assessment.pk: sorted(
                set(revision_ids_by_assessment[assessment.pk])
                - {
                    created_id
                    for job in jobs_by_assessment[assessment.pk]
                    for created_id in job.created_revision_ids
                }
            )
            for assessment in assessments
        }
        outside_rows = cls.describe_stacks_outside_lando(
            phab,
            {
                linked_id
                for outside_ids in outside_ids_by_assessment.values()
                for linked_id in outside_ids
            },
        )

        return tuple(
            UpliftAssessmentCard(
                assessment=assessment,
                form=UpliftAssessmentForm(instance=assessment),
                is_linked=assessment == linked_assessment,
                revision_ids=revision_ids_by_assessment[assessment.pk],
                requested_revision_ids=assessment.requested_revision_ids(),
                train_groups=cls.group_by_train(
                    [
                        UpliftTrainRow(
                            train=job.target_repo.name,
                            tip_revision_id=(job.created_revision_ids or [None])[-1],
                            outcome=UpliftTrainOutcome.for_job(job),
                            job=job,
                        )
                        for job in jobs_by_assessment[assessment.pk]
                    ]
                    + [
                        outside_rows.get(
                            linked_id,
                            UpliftTrainRow(
                                train=None,
                                tip_revision_id=linked_id,
                                outcome=UpliftTrainOutcome.SUBMITTED_OUTSIDE_LANDO,
                            ),
                        )
                        for linked_id in outside_ids_by_assessment[assessment.pk]
                    ]
                ),
            )
            for assessment in assessments
        )

    @staticmethod
    def group_by_train(
        rows: Sequence[UpliftTrainRow],
    ) -> tuple[UpliftTrainGroup, ...]:
        """Group `rows` by train, in the order the trains first appear.

        A failed job and the stack later submitted to resolve it are not linked
        in Lando's data, so they are shown together by train, not paired.
        """
        rows_by_train: dict[str | None, list[UpliftTrainRow]] = {}
        for row in rows:
            rows_by_train.setdefault(row.train, []).append(row)

        return tuple(
            UpliftTrainGroup(train=train, rows=tuple(train_rows))
            for train, train_rows in rows_by_train.items()
        )

    @staticmethod
    def describe_stacks_outside_lando(
        phab: PhabricatorClient | None, revision_ids: set[int]
    ) -> dict[int, UpliftTrainRow]:
        """Return a train row for each stack tip no Lando job created.

        Lando only records which assessment such a stack carries, so its train
        comes from Phabricator. A failed lookup leaves it unknown.
        """
        if phab is None or not revision_ids:
            return {}

        logger.debug("Looking up the trains of %s in Phabricator.", revision_ids)
        try:
            revisions = get_revisions_by_id(phab, sorted(revision_ids))
            repo_phids = sorted(
                {
                    revision["fields"]["repositoryPHID"]
                    for revision in revisions.values()
                    if revision["fields"].get("repositoryPHID")
                }
            )
            repositories = (
                phab.call_conduit(
                    "diffusion.repository.search",
                    constraints={"phids": repo_phids},
                    limit=len(repo_phids),
                )["data"]
                if repo_phids
                else []
            )

            # The latest diff's commit author says whether hackbot submitted it.
            diffs = get_diffs_by_phid(
                phab,
                sorted(
                    {
                        revision["fields"]["diffPHID"]
                        for revision in revisions.values()
                        if revision["fields"].get("diffPHID")
                    }
                ),
            )
        except PhabricatorAPIException, ValueError:
            logger.warning(
                "Could not look up the trains of %s.", revision_ids, exc_info=True
            )
            return {}

        short_names = {
            repository["phid"]: repository["fields"]["shortName"]
            for repository in repositories
        }

        # Name a train the way Lando's jobs do, falling back to Phabricator's.
        lando_names = dict(
            Repo.objects.filter(short_name__in=short_names.values()).values_list(
                "short_name", "name"
            )
        )

        rows = {}
        for revision in revisions.values():
            short_name = short_names.get(revision["fields"].get("repositoryPHID"))
            diff = diffs.get(revision["fields"].get("diffPHID"))

            # `DISALLOWED_AUTHOR_EMAILS` is how Lando recognises hackbot's commits,
            # and hackbot submits uplift stacks to resolve a job's merge conflict.
            by_hackbot = diff is not None and diff_has_disallowed_author(diff)

            rows[revision["id"]] = UpliftTrainRow(
                train=lando_names.get(short_name, short_name),
                tip_revision_id=revision["id"],
                outcome=(
                    UpliftTrainOutcome.CONFLICT_RESOLVED_BY_HACKBOT
                    if by_hackbot
                    else UpliftTrainOutcome.SUBMITTED_WITH_MOZ_PHAB
                ),
            )

        return rows

    def can_create_submission(request: WSGIRequest) -> bool:
        """Return `True` when the user can submit uplift jobs."""
        return (
            request.user.is_authenticated and request.user.profile.phabricator_api_key
        )
