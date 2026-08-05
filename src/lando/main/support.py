from django.conf import settings
from django.core.files.storage import storages
from storages.backends.gcloud import GoogleCloudStorage

from lando.api.legacy.revisions import select_diff_author


class CachedGoogleCloudStorage(GoogleCloudStorage):
    """
    Extends GoogleCloudStorage to include support for django-compressor.

    See https://django-compressor.readthedocs.io/en/stable/remote-storages.html.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.local_storage = storages.create_storage(
            {"BACKEND": "compressor.storage.CompressorFileStorage"}
        )

    def save(self, name, content):  # noqa: ANN001, ANN201
        self.local_storage.save(name, content)
        super().save(name, self.local_storage._open(name))
        return name


class LegacyAPIException(Exception):
    def __init__(self, status, detail, extra=None):  # noqa: ANN001
        self.status = status
        self.detail = detail
        self.extra = extra
        self.json_detail = {
            "detail": self.detail,
        }
        if self.extra:
            self.json_detail.update(self.extra)


def get_revisions_with_disallowed_authors(revisions: dict[str, dict]) -> list[dict]:
    """Return a list of revisions with disallowed authors.

    An author is disallowed if it is present in the DISALLOWED_AUTHOR_EMAILS setting.
    """
    return [r for r in revisions.values() if revision_has_disallowed_author(r)]


def revision_has_disallowed_author(revision: dict) -> bool:
    """Return True if a revision has a disallowed author, otherwise False.

    An author is disallowed if it is present in the DISALLOWED_AUTHOR_EMAILS setting.
    """
    return (
        revision["diff"]["author"]["email"].strip().lower()
        in settings.DISALLOWED_AUTHOR_EMAILS
    )


def diff_has_disallowed_author(diff: dict) -> bool:
    """Return True if a diff has a disallowed author, otherwise False.

    An author is disallowed if it is present in the DISALLOWED_AUTHOR_EMAILS setting.
    """
    return (
        select_diff_author(diff)[1] or ""
    ).strip().lower() in settings.DISALLOWED_AUTHOR_EMAILS
