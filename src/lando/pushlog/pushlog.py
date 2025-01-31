import logging
from contextlib import contextmanager
from typing import Optional

from django.db import transaction

from lando.main.models.repo import Repo
from lando.main.scm.commit import Commit as SCMCommit
from lando.pushlog.models.commit import Commit
from lando.pushlog.models.push import Push

logger = logging.getLogger(__name__)


@contextmanager
def PushLogForRepo(repo: Repo, user: str):
    """
    Context manager allowing to incrementally build push information, and only submit it
    when complete.

    WARNING: Do not use record_push() on the returned PushLog, as the context manager
    will take care of it automatically. Calling it separately may lead to duplicates.
    """
    pushlog = PushLog(repo, user)
    try:
        yield pushlog
    except Exception as e:
        logger.error(f"Push aborted for {user}: {e}")
        raise (e)
    else:
        # Only record the whole push on success.
        try:
            pushlog.record_push()
        except Exception as e:
            # We keep a record of the Pushlog in the extra, in addition to printing
            # details in the log.
            logger.error(
                f"Failed to record push log due to: {e}\n{pushlog}",
                extra={"pushlog": pushlog},
            )
            raise e


class PushLog:
    repo: Repo
    push: Push
    user: str

    confirmed: bool = False

    commits: list

    def __init__(
        self,
        repo: Repo,
        user: str,
        commits: list = [],
    ):
        self.repo = repo
        self.user = user

        if not commits:
            # We cannot us the default value of the argument as a mutable type, and will
            # get reused on every initialisation.
            commits = []
        self.commits = commits

    def __repr__(self):
        return (
            f"{self.__class__.__name__}({self.repo!r}, {self.user}, {self.commits!r})"
        )

    def add_commit(self, scm_commit: SCMCommit) -> Commit:
        # We create a commit object in memory, but will only write it into the DB when
        # the whole push is done, and we have a transaction open.
        logger.debug(f"Adding commit {scm_commit} to current push ...")
        commit = Commit.from_scm_commit(self.repo, scm_commit)
        self.commits.append(commit)

        return commit

    def remove_tip_commit(self) -> Commit:
        """Remove the tip commit from the PushLog, returning it."""
        tip_commit = self.commits[-1]
        self.commits.remove(tip_commit)
        return tip_commit

    def confirm(self, value: bool = True):
        self.confirmed = value

    @transaction.atomic
    def record_push(self) -> Optional[Push]:
        """Flush all push data to the database.

        This will only happen if the push has been confirm()ed first.

        Don't use directly if using a PushLogForRepo ContextManager.
        """
        if not self.confirmed:
            logger.warning(
                f"Push for {self.repo.url} wasn't confirmed; aborting ...\n{self}",
                extra={"pushlog": self},
            )
            return None

        push = Push.objects.create(repo=self.repo, user=self.user)
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

        push.save()
        logger.info(f"Successfully saved {push}")

        return push
