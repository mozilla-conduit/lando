import datetime
import logging
from typing import Annotated, Literal, Union

from django.contrib.auth.models import User
from django.db import transaction
from ninja import (
    NinjaAPI,
    Schema,
)
from ninja.responses import codes_4xx
from ninja.security import HttpBearer
from pydantic import Field

from lando.main.models.automation_job import (
    AutomationAction,
    AutomationJob,
)
from lando.main.models.landing_job import LandingJobStatus
from lando.main.models.repo import Repo

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

        try:
            user = User.objects.get(email=user_agent)
        except User.DoesNotExist:
            raise APIPermissionDenied(f"No user found for `User-Agent` {user_agent}")

        decrypted_token = user.profile.lando_api_key
        if not decrypted_token or not token or decrypted_token != token:
            raise APIPermissionDenied("API token is invalid.")

        # Django-Ninja sets `request.auth` to the verified token, since
        # some APIs may have authentication without user management. Our
        # API tokens always correspond to a specific user, so set that on
        # the request here.
        request.user = user

        return token


api = NinjaAPI(auth=HeadlessAPIAuthentication())


@api.exception_handler(APIPermissionDenied)
def on_invalid_token(request, exc):
    """Create a JSON response when the API returns a 401."""
    return api.create_response(request, {"details": str(exc)}, status=401)


class AddCommitAction(Schema):
    """Create a new commit the given patch content."""

    action: Literal["add-commit"]
    content: str


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


@api.post("/repo/{repo_name}/{branch}", response={202: JobStatus, codes_4xx: ApiError})
def post_repo_actions(
    request, repo_name: str, branch: str, operation: AutomationOperation
):
    """API endpoint to handle submission of pushes."""
    # Get the repo object.
    try:
        repo = Repo.objects.get(name=repo_name)
    except Repo.DoesNotExist:
        error = f"Repo {repo_name} does not exist."
        logger.info(error)
        return 404, {"details": error}

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
        f"{len(operation.actions)} actions."
    )

    return 202, automation_job.to_api_status()


@api.get("/job/{int:job_id}", response={200: JobStatus, codes_4xx: ApiError})
def get_job_status(request, job_id: int):
    """Retrieve the status of a job by ID."""
    try:
        automation_job = AutomationJob.objects.get(id=job_id)
    except AutomationJob.DoesNotExist:
        error = f"Automation job {job_id} does not exist."
        logger.info(error)
        return 404, {"details": error}

    logger.info(f"Retrieved status for job {automation_job.id}.")

    return 200, automation_job.to_api_status()
