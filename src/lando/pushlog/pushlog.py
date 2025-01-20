import logging
from contextlib import contextmanager

from django.db import transaction

from lando.main.models.repo import Repo
from lando.pushlog.models.commit import Commit
from lando.pushlog.models.push import Push

logger = logging.getLogger(__name__)


@contextmanager
def PushLogForRepo(repo: Repo):
    pushlog = PushLog(repo)
    try:
        yield pushlog
    except Exception as e:
        raise (e)
    else:
        # Only record the whole push on success.
        try:
            pushlog.record_push()
        except Exception as e:
            logger.error(
                f"Failed to record push log due to {e}", extra={"pushlog": pushlog}
            )
            raise e


class PushLog:
    repo: Repo
    push: Push

    commits: list

    def __repr__(self):
        return f"<{self.__class__.__name__}({self.repo}, {self.commits})>"

    def __init__(self, repo: Repo):
        self.repo = repo
        self.commits = []

    # def add_commit(self, revision: Revision) -> Commit:
    def add_commit(self, hash: str):
        # XXX need a container with
        # author
        # date
        # desc
        # files
        # PARENTS
        self.commits.append(hash)

    @transaction.atomic
    def record_push(self):
        push = Push.objects.create(self.repo)
        for commit in self.commits:
            commit = Commit.objects.create(self.repo, hash=hash)
            push.commits.add(commit)

        push.save()
