import datetime
import logging
from io import StringIO
from typing import Annotated, Literal, Union

from django.db import transaction
from ninja import (
    NinjaAPI,
    Schema,
)
from ninja.responses import codes_4xx
from ninja.security import HttpBearer
from pydantic import Field, TypeAdapter

from lando.api.legacy.hgexports import (
    PATCH_HELPER_MAPPING,
    PatchFormat,
)
from lando.headless_api.models.automation_job import (
    AutomationAction,
    AutomationJob,
)
from lando.headless_api.models.tokens import ApiToken
from lando.main.models.landing_job import LandingJobAction, LandingJobStatus
from lando.main.models.repo import Repo
from lando.main.scm.abstract_scm import AbstractSCM
from lando.main.scm.exceptions import (
    PatchConflict,
)

logger = logging.getLogger(__name__)


class APIPermissionDenied(Exception):
    """Custom exception type to allow JSON responses for invalid auth."""

    pass


class HeadlessAPIAuthentication(HttpBearer):
    """Authentication class to verify API token."""

    def authenticate(self, request, token: str) -> str:
        user_agent = request.headers.get("User-Agent")
        if not user_agent:
            raise APIPermissionDenied("`User-Agent` header is required.")

        if not user_agent.startswith("Lando-User/"):
            raise APIPermissionDenied("Incorrect `User-Agent` format.")

        try:
            api_token = ApiToken.verify_token(token)
        except ValueError as exc:
            raise APIPermissionDenied(str(exc))

        if not api_token.user.profile.is_automation_user:
            raise APIPermissionDenied(
                f"User {api_token.user.email} is not permitted to make automation changes."
            )

        # Django-Ninja sets `request.auth` to the verified token, since
        # some APIs may have authentication without user management. Our
        # API tokens always correspond to a specific user, so set that on
        # the request here.
        request.user = api_token.user

        return api_token


api = NinjaAPI(auth=HeadlessAPIAuthentication())


@api.exception_handler(APIPermissionDenied)
def on_invalid_token(request, exc):
    """Create a JSON response when the API returns a 401."""
    return api.create_response(request, {"details": str(exc)}, status=401)


class AutomationActionException(Exception):
    """Exception thrown by automation actions."""

    def __init__(self, message: str, job_action: LandingJobAction, is_fatal: bool):
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
                job_action=LandingJobAction.FAIL,
                is_fatal=True,
            )

        try:
            patch_helper = helper_class(StringIO(self.content))
        except ValueError as exc:
            message = (
                "Could not parse patch in `add-commit`, "
                f"action #{index}.: {str(exc)}"
            )
            raise AutomationActionException(
                message=message,
                job_action=LandingJobAction.FAIL,
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
                job_action=LandingJobAction.FAIL,
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
                job_action=LandingJobAction.FAIL,
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
                message=message, job_action=LandingJobAction.FAIL, is_fatal=False
            )
        except Exception as e:
            message = (
                f"Aborting, could not apply patch buffer from `add-commit`, "
                f"action #{index}."
                f"\n{e}"
            )
            raise AutomationActionException(
                message=message, job_action=LandingJobAction.FAIL, is_fatal=False
            )

        return True


class MergeOntoAction(Schema):
    """Merge the current branch into the target commit."""

    action: Literal["merge-onto"]
    target: str
    message: str


class TagAction(Schema):
    """Create a new tag with the given name."""

    action: Literal["tag"]
    name: str


class AddBranchAction(Schema):
    """Create a new branch at the given commit."""

    action: Literal["add-branch"]
    name: str
    commit: str


Action = Union[AddCommitAction, MergeOntoAction, AddBranchAction, TagAction]


def resolve_action(action_data: dict) -> Action:
    """Convert a raw `dict` into an `Action` object."""
    return TypeAdapter(Action).validate_python(action_data)


class AutomationOperation(Schema):
    """Represents the body of an automation API operation request."""

    # `Annotated` here to specify `min_items=1`.
    actions: Annotated[list[Action], Field(min_items=1)]


class ApiError(Schema):
    """Response format for an error within the API."""

    details: str


class JobStatus(Schema):
    """Response format of a job status report."""

    job_id: int
    status_url: str
    message: str
    created_at: datetime.datetime


@api.post("/repo/{repo_name}", response={202: JobStatus, codes_4xx: ApiError})
def post_repo_actions(request, repo_name: str, operation: AutomationOperation):
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
        return 403, {"details": error}

    with transaction.atomic():
        automation_job = AutomationJob.objects.create(
            status=LandingJobStatus.SUBMITTED,
            requester_email=request.user.email,
            target_repo=repo,
        )

        for index, action in enumerate(operation.actions):
            AutomationAction.objects.create(
                job_id=automation_job,
                action_type=action.action,
                data=action.dict(),
                order=index,
            )

    logger.info(
        f"Created automation job {automation_job.id} with "
        f"{len(operation.actions)} actions.",
        extra={"user": request.user.email},
    )

    return 202, automation_job.to_api_status()


@api.get("/job/{int:job_id}", response={200: JobStatus, codes_4xx: ApiError})
def get_job_status(request, job_id: int):
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
