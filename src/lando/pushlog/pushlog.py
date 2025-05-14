import logging
from contextlib import contextmanager
from typing import ContextManager, Optional

from django.db import transaction

from lando.main.models.repo import Repo
from lando.main.scm.commit import CommitData
from lando.pulse.pulse import PulseNotifier
from lando.pushlog.models import Commit, Push, Tag

logger = logging.getLogger(__name__)


class PushLog:
    """
    Aggregate a list of Commits and Tag and record push information.
    """

    repo: Repo
    push: Push
    user: str
    branch: str | None = None

    is_confirmed: bool = False
    is_recorded: bool = False

    commits: list[Commit]
    tags: list[Tag]

    def __init__(
        self,
        repo: Repo,
        user: str,
        branch: str | None = None,
        commits: list[Commit] | None = None,
        tags: list[Tag] | None = None,
    ):
        self.repo = repo
        self.user = user
        self.branch = branch

        self.commits = commits or []

        self.tags = tags or []

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}({self.repo!r}, {self.user}, {self.commits!r})"
        )

    def add_commit(self, scm_commit: CommitData) -> Commit:
        """Add a new commit to the Pushlog, for later recording in the DB.

        We create a commit object in memory, but will only write it into the DB when
        the whole push is done, and we have a transaction open.
        """
        logger.debug(f"Adding commit {scm_commit} to current push ...")
        commit = Commit.from_scm_commit(self.repo, scm_commit)
        self.commits.append(commit)

        return commit

    def add_tag(self, tag_name: str, scm_commit: CommitData) -> Tag:
        """Add a new tag to the Pushlog, for later recording in the DB."""
        logger.debug(f"Adding tag {str} to {scm_commit.hash} to current push ...")

        tag = Tag.for_scm_commit(repo=self.repo, name=tag_name, scm_commit=scm_commit)
        self.tags.append(tag)

        return tag

    def confirm(self, value: bool = True):
        """Mark the push as confirmed and ready to record.

        While the PushLogForRepo ContextManager is used to capture unhandled exceptions
        and make sure the Push is otherwise recorded, we also need a way for the code to
        signal that a Push is read, rather than other (handled) failure
        cases that should not lead to the record being written.
        """
        self.is_confirmed = value

    @transaction.atomic
    def record_push(self) -> Optional[Push]:
        """Flush all push data to the database.

        This will only happen if the push has been confirm()ed first.

        Don't use directly if using a PushLogForRepo ContextManager.
        """
        if self.is_recorded:
            raise RuntimeError("Trying to record already recorded push.")

        if not self.is_confirmed:
            logger.warning(
                f"Push for {self.repo.url} wasn't confirmed; aborting ...\n{self}",
                extra={"pushlog": self},
            )
            return None

        push = Push.objects.create(repo=self.repo, user=self.user, branch=self.branch)
        logger.debug(f"Creating push {push.push_id} to {push.repo_url} ...")
        logger.debug(
            f"Commits in push {push.push_id} to {push.repo_url}: {self.commits}"
        )

        for commit in self.commits:
            # We need to save the commit before we can associate files to it.
            logger.debug(
                f"Saving commit {commit.hash} for push {push.push_id} to {push.repo_url} ..."
            )
            commit.save()
            push.commits.add(commit)

        for tag in self.tags:
            logger.debug(
                f"Saving tag {tag} for push {push.push_id} to {push.repo_url} ..."
            )
            tag.save()
            push.tags.add(tag)

        push.save()
        self.push = push
        self.is_recorded = True

        logger.info(f"Successfully saved {push}")

        try:
            # XXX: share this instance
            notifier = PulseNotifier()
            notifier.notify_push(push)
        except Exception as exc:
            logger.warning(f"Failed to notify push {push}: {exc}")

        return push


class NoOpPushLog(PushLog):
    """A noop PushLog object to use when disabled without having to resort to ifs."""

    def add_commit(self, scm_commit: CommitData) -> Commit:
        # Satisfy the return value from the interface, but do nothing else.
        return Commit.from_scm_commit(self.repo, scm_commit)

    def confirm(self, value: bool = True):
        pass

    def record_push(self) -> Optional[Push]:
        pass


@contextmanager
def PushLogForRepo(
    repo: Repo, user: str, branch: str | None = None
) -> ContextManager[PushLog]:
    """
    Context manager allowing to incrementally build push information, and only submit it
    when complete.

    WARNING: Do not use record_push() on the returned PushLog, as the context manager
    will take care of it automatically. Calling it multiple times will raise a RuntimeError.
    """
    if repo.pushlog_disabled:
        pushlog = NoOpPushLog(repo, user)
    else:
        pushlog = PushLog(repo, user, branch=branch)

    try:
        yield pushlog
    except Exception as exc:
        logger.error(f"Push aborted for {user}: {exc}")
        raise (exc)

    # Only record the whole push on success.
    try:
        pushlog.record_push()
    except Exception as exc:
        # We keep a record of the Pushlog in the extra, in addition to printing
        # details in the log.
        logger.error(
            f"Failed to record push log due to: {exc}\n{pushlog}",
            extra={"pushlog": pushlog},
        )
        raise exc
