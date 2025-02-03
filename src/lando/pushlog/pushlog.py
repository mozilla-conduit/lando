import logging
from contextlib import contextmanager

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

    commits: list
    # ManyToMany relationships that needs to be stored separately until Commits are
    # save(), and the association can be made.
    files: dict[str, list[str]]
    parents: dict[str, list[str]]

    def __init__(
        self,
        repo: Repo,
        user: str,
        commits: list = [],
        files: dict[str, list[str]] = {},
        parents: dict[str, list[str]] = {},
    ):
        self.repo = repo
        self.user = user

        if not commits:
            # We cannot us the default value of the argument as a mutable type, and will
            # get reused on every initialisation.
            commits = []
        self.commits = commits

        if not files:
            # Same a commits above.
            files = {}
        self.files = files

        if not parents:
            # Same a commits above.
            parents = {}
        self.parents = parents

    def __repr__(self):
        return (
            f"{self.__class__.__name__}({self.repo!r}, {self.user}, {self.commits!r})"
        )

    def add_commit(self, scm_commit: SCMCommit) -> Commit:
        # We create a commit object in memory, but will only write it into the DB when
        # the whole push is done, and we have a transaction open.
        commit = Commit.from_scm_commit(self.repo, scm_commit)
        self.commits.append(commit)

        # We can only attach parents and files to the Commit when it exists in the DB,
        # so we hold them here in the meantime.
        self.parents[scm_commit.hash] = scm_commit.parents
        self.files[scm_commit.hash] = scm_commit.files

        return commit

    @transaction.atomic
    def record_push(self) -> Push:
        """Flush all push data to the database.

        Don't use directly if using a PushLogForRepo.
        """
        push = Push.objects.create(repo=self.repo, user=self.user)
        for commit in self.commits:
            # We need to save the commit before we can associate files to it.
            commit.save()

            commit.add_parents(self.parents[commit.hash])
            commit.add_files(self.files[commit.hash])
            push.commits.add(commit)

        push.save()

        return push
