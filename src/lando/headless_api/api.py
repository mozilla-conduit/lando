import base64
import binascii
import datetime
import logging
from io import StringIO
from typing import Annotated, Literal

from django.core.exceptions import PermissionDenied
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.http import HttpResponse
from ninja import (
    NinjaAPI,
    Schema,
)
from ninja.responses import codes_4xx
from ninja.security import HttpBearer
from pydantic import Field, TypeAdapter
from pydantic.types import StringConstraints

from lando.headless_api.models.automation_job import (
    AutomationAction,
    AutomationJob,
)
from lando.headless_api.models.tokens import ApiToken
from lando.main.models import JobAction, JobStatus, Repo
from lando.main.scm import (
    AbstractSCM,
    MergeStrategy,
    PatchConflict,
)
from lando.main.scm.helpers import (
    PATCH_HELPER_MAPPING,
    PatchFormat,
)

logger = logging.getLogger(__name__)


class APIPermissionDenied(PermissionDenied):
    """Custom exception type to allow JSON responses for invalid auth."""

    pass


class HeadlessAPIAuthentication(HttpBearer):
    """Authentication class to verify API token."""

    def authenticate(self, request: WSGIRequest, token: str) -> ApiToken:
        user_agent = request.headers.get("User-Agent")
        if not user_agent:
            raise APIPermissionDenied("`User-Agent` header is required.")

        if not user_agent.startswith("Lando-User/"):
            raise APIPermissionDenied("Incorrect `User-Agent` format.")

        try:
            api_key = ApiToken.verify_token(token)
        except ValueError as exc:
            raise APIPermissionDenied(str(exc))

        if not api_key.user.has_perm("headless_api.add_automationjob"):
            raise APIPermissionDenied(
                f"User {api_key.user.email} is not permitted to make automation changes."
            )

        # Django-Ninja sets `request.auth` to the verified token, since
        # some APIs may have authentication without user management. Our
        # API tokens always correspond to a specific user, so set that on
        # the request here.
        request.user = api_key.user

        return api_key


api = NinjaAPI(auth=HeadlessAPIAuthentication(), urls_namespace="headless-api")


@api.exception_handler(APIPermissionDenied)
def on_invalid_token(request: WSGIRequest, exc: Exception) -> HttpResponse:
    """Create a JSON response when the API returns a 401."""
    return api.create_response(request, {"details": str(exc)}, status=401)


class AutomationActionException(Exception):
    """Exception thrown by automation actions."""

    def __init__(self, message: str, job_action: JobAction, is_fatal: bool):
        super().__init__()
        self.message = message
        self.job_status = job_action
        self.is_fatal = is_fatal


class AddCommitAction(Schema):
    """Create a new commit the given patch content."""

    action: Literal["add-commit"]
    content: str
    patch_format: PatchFormat

    def process(
        self, job: AutomationJob, repo: Repo, scm: AbstractSCM, index: int
    ) -> bool:
        """Add a commit to the repo."""
        try:
            helper_class = PATCH_HELPER_MAPPING[self.patch_format]
        except KeyError:
            raise AutomationActionException(
                message=(
                    f"Could not find patch helper for {self.patch_format} "
                    f"in `add-commit`, action #{index}"
                ),
                job_action=JobAction.FAIL,
                is_fatal=True,
            )

        try:
            patch_helper = helper_class.from_string_io(StringIO(self.content))
        except ValueError as exc:
            message = (
                f"Could not parse patch in `add-commit`, action #{index}.: {str(exc)}"
            )
            raise AutomationActionException(
                message=message,
                job_action=JobAction.FAIL,
                is_fatal=True,
            )

        try:
            date = patch_helper.get_header("Date")
        except ValueError:
            message = (
                "Could not parse `Date` header from patch in `add-commit`, "
                f"action #{index}."
            )
            raise AutomationActionException(
                message=message,
                job_action=JobAction.FAIL,
                is_fatal=True,
            )

        try:
            name, email = patch_helper.parse_author_information()
        except ValueError:
            message = (
                "Could not parse authorship information from patch in `add-commit`, "
                f"action #{index}."
            )
            raise AutomationActionException(
                message=message,
                job_action=JobAction.FAIL,
                is_fatal=True,
            )

        try:
            scm.apply_patch(
                patch_helper.get_diff(),
                patch_helper.get_commit_description(),
                f"{name} <{email}>",
                date,
            )
        except PatchConflict as exc:
            message = (
                f"Merge conflict while applying patch in `add-commit`, "
                f"action #{index}.\n\n"
                f"{str(exc)}"
            )
            raise AutomationActionException(
                message=message, job_action=JobAction.FAIL, is_fatal=False
            )
        except Exception as e:
            message = (
                f"Aborting, could not apply patch buffer from `add-commit`, "
                f"action #{index}."
                f"\n{e}"
            )
            raise AutomationActionException(
                message=message, job_action=JobAction.FAIL, is_fatal=False
            )

        return True


class AddCommitBase64Action(Schema):
    """Create a new commit from the given base64 patch content."""

    action: Literal["add-commit-base64"]
    content: str

    def process(
        self, job: AutomationJob, repo: Repo, scm: AbstractSCM, index: int
    ) -> bool:
        """Apply the base64 encoded `git format-patch` to the repo."""
        try:
            patch_bytes = base64.b64decode(self.content)
        except binascii.Error as exc:
            message = (
                f"Aborting, could not decode patch from base64 in `add-commit-base64`, "
                f"action #{index}."
                f"\n{exc}"
            )
            raise AutomationActionException(
                message=message, job_action=JobAction.FAIL, is_fatal=True
            )

        try:
            scm.apply_patch_git(patch_bytes)
        except Exception as exc:
            message = (
                f"Aborting, could not apply patch in `add-commit-base64` action #{index}."
                f"\n{exc}"
            )
            raise AutomationActionException(
                message=message, job_action=JobAction.FAIL, is_fatal=True
            )

        return True


class CreateCommitAction(Schema):
    """Create a new commit from a diff and metadata."""

    action: Literal["create-commit"]
    author: str
    commitmsg: str
    date: datetime.datetime
    diff: str

    def process(
        self, job: AutomationJob, repo: Repo, scm: AbstractSCM, index: int
    ) -> bool:
        """Create a new commit from a diff and metadata."""
        try:
            scm.apply_patch(
                self.diff,
                self.commitmsg,
                self.author,
                self.date.isoformat(),
            )
        except PatchConflict as exc:
            message = (
                f"Merge conflict while creating commit in `create-commit`, "
                f"action #{index}.\n\n"
                f"{str(exc)}"
            )
            raise AutomationActionException(
                message=message, job_action=JobAction.FAIL, is_fatal=True
            )
        except Exception as e:
            message = (
                f"Aborting, could not create commit from `create-commit`, "
                f"action #{index}."
                f"\n{e}"
            )
            raise AutomationActionException(
                message=message, job_action=JobAction.FAIL, is_fatal=True
            )

        return True


class MergeOntoAction(Schema):
    """Merge the current branch into the target commit."""

    action: Literal["merge-onto"]
    commit_message: str
    strategy: MergeStrategy | None
    target: str

    def process(
        self, job: AutomationJob, repo: Repo, scm: AbstractSCM, index: int
    ) -> bool:
        """Perform a merge on the repo."""
        try:
            scm.merge_onto(
                commit_message=self.commit_message,
                target=self.target,
                strategy=self.strategy,
            )
        except Exception as exc:
            message = (
                f"Aborting, could not perform `merge-onto`, action #{index}.\n{exc}"
            )
            raise AutomationActionException(
                message=message, job_action=JobAction.FAIL, is_fatal=True
            ) from exc

        return True


class TagAction(Schema):
    """Create a new tag with the given name."""

    action: Literal["tag"]
    name: str
    target: str | None = None

    def process(
        self, job: AutomationJob, repo: Repo, scm: AbstractSCM, index: int
    ) -> bool:
        """Add a new tag to the repo."""
        try:
            scm.tag(name=self.name, target=self.target)
        except Exception as exc:
            message = f"Aborting, could not perform `tag`, action #{index}\n{exc}"
            raise AutomationActionException(
                message=message, job_action=JobAction.FAIL, is_fatal=True
            )

        return True


class AddBranchAction(Schema):
    """Create a new branch at the given commit."""

    action: Literal["add-branch"]
    name: str
    commit: str

    def process(
        self, job: AutomationJob, repo: Repo, scm: AbstractSCM, index: int
    ) -> bool:
        """Add a new branch to the repo."""
        raise NotImplementedError()


class MergeRemoteAction(Schema):
    """Merge changes from a remote repository"""

    action: Literal["merge-remote"]
    commit_message: str
    repo: str
    commit: Annotated[str, StringConstraints(pattern="[0-9a-fA-F]{40}")]
    allow_unrelated: bool = False

    def process(
        self, job: AutomationJob, repo: Repo, scm: AbstractSCM, index: int
    ) -> bool:
        try:
            scm.merge_remote(
                commit_message=self.commit_message,
                remote=self.repo,
                commit=self.commit,
                allow_unrelated=self.allow_unrelated,
            )
        except Exception as exc:
            message = f"Aborting, could not `merge-remote`, action #{index}.\n{exc}"
            raise AutomationActionException(
                message=message, job_action=JobAction.FAIL, is_fatal=True
            ) from exc

        return True


Action = (
    AddCommitAction
    | AddCommitBase64Action
    | CreateCommitAction
    | MergeOntoAction
    | AddBranchAction
    | TagAction
    | MergeRemoteAction
)

ActionAdapter = TypeAdapter(Action)


def resolve_action(action_data: dict) -> Action:
    """Convert a raw `dict` into an `Action` object."""
    return ActionAdapter.validate_python(action_data)


class RelBranchSpecifier(Schema):
    """Metadata requried to specify the RelBranch for pushing."""

    # Name of the RelBranch for pushing.
    branch_name: str

    # Commit to point the RelBranch to, if it does not exist yet.
    commit_sha: str | None = None


class AutomationOperation(Schema):
    """Represents the body of an automation API operation request."""

    # `Annotated` here to specify `min_items=1`.
    actions: Annotated[list[Action], Field(min_items=1)]

    # Optional field indicating the changes should be pushed to a RelBranch.
    relbranch: RelBranchSpecifier | None = None


class ApiError(Schema):
    """Response format for an error within the API."""

    details: str


class JobStatusResponse(Schema):
    """Response format of a job status report."""

    job_id: int
    status_url: str
    message: str
    created_at: datetime.datetime
    status: str
    error: str | None


@api.post("/repo/{repo_name}", response={202: JobStatusResponse, codes_4xx: ApiError})
def post_repo_actions(
    request: WSGIRequest, repo_name: str, operation: AutomationOperation
) -> tuple[int, dict]:
    """API endpoint to handle submission of pushes."""
    # Get the repo object.
    try:
        repo = Repo.objects.get(name=repo_name)
    except Repo.DoesNotExist:
        error = f"Repo {repo_name} does not exist."
        logger.info(
            error,
            extra={"user": request.user.email, "token": request.auth.token_prefix},
        )
        return 404, {"details": error}

    if not repo.automation_enabled:
        error = f"Repo {repo_name} is not enabled for automation."
        logger.info(
            error,
            extra={"user": request.user.email, "token": request.auth.token_prefix},
        )
        return 400, {"details": error}

    with transaction.atomic():
        automation_job = AutomationJob.objects.create(
            status=JobStatus.SUBMITTED,
            requester_email=request.user.email,
            target_repo=repo,
        )

        if operation.relbranch:
            automation_job.relbranch_name = operation.relbranch.branch_name
            automation_job.relbranch_commit_sha = operation.relbranch.commit_sha
            automation_job.save()

        for index, action in enumerate(operation.actions):
            AutomationAction.objects.create(
                job_id=automation_job,
                action_type=action.action,
                data=action.model_dump(mode="json"),
                order=index,
            )

    logger.info(
        f"Created automation job {automation_job.id} with "
        f"{len(operation.actions)} actions.",
        extra={"user": request.user.email},
    )

    return 202, automation_job.to_api_status()


@api.get("/job/{int:job_id}", response={200: JobStatusResponse, codes_4xx: ApiError})
def get_job_status(request: WSGIRequest, job_id: int) -> tuple[int, dict]:
    """Retrieve the status of a job by ID."""
    try:
        automation_job = AutomationJob.objects.get(id=job_id)
    except AutomationJob.DoesNotExist:
        error = f"Automation job {job_id} does not exist."
        logger.info(
            error,
            extra={"user": request.user.email, "token": request.auth.token_prefix},
        )
        return 404, {"details": error}

    logger.debug(
        f"Retrieved status for job {automation_job.id}.",
        extra={"user": request.user.email, "token": request.auth.token_prefix},
    )

    return 200, automation_job.to_api_status()


class RepoInfoReponse(Schema):
    """Response format for the repo lookup endpoint."""

    repo_url: str
    branch_name: str
    scm_level: str


def strip_app_from_permission(permission_str: str) -> str:
    """Strip the Django app name from a permission.

    Assumes the permission takes the form `<app>.<permission`.

    >>> strip_app_from_permission("main.scm_level_3")
    "scm_level_3"
    """
    _app, permission = permission_str.split(".")
    return permission


@api.get("/repoinfo/{short_name}", response={200: RepoInfoReponse, codes_4xx: ApiError})
def get_repo_by_short_name(request: WSGIRequest, short_name: str) -> tuple[int, dict]:
    """Retrieve repo information by short name.

    Used by merge day automation.
    """
    try:
        repo = Repo.objects.get(short_name=short_name)
    except Repo.DoesNotExist:
        error = f"Repo with short name {short_name} does not exist."
        logger.info(
            error,
            extra={"user": request.user.email, "token": request.auth.token_prefix},
        )
        return 404, {"details": error}

    stripped_permission = strip_app_from_permission(repo.required_permission)

    return 200, RepoInfoReponse(
        repo_url=repo.url,
        branch_name=repo.default_branch,
        scm_level=stripped_permission,
    )
