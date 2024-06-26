from unittest.mock import MagicMock

from django.core.files.storage import storages
from django.http import HttpResponse
from storages.backends.gcloud import GoogleCloudStorage

from lando import settings
from lando.api.legacy.phabricator import PhabricatorClient


class CachedGoogleCloudStorage(GoogleCloudStorage):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.local_storage = storages.create_storage(
            {"BACKEND": "compressor.storage.CompressorFileStorage"}
        )

    def save(self, name, content):
        self.local_storage.save(name, content)
        super().save(name, self.local_storage._open(name))
        return name


class ProblemException(Exception):
    def __init__(
        self,
        status=500,
        title=None,
        detail=None,
        type=None,
        instance=None,
        headers=None,
        ext=None,
    ):
        # TODO: this should be reimplemented as either middleware or HttpResponse return values.
        super().__init__(detail)
        self.detail = detail
        self.ext = ext
        self.headers = headers
        self.instance = instance
        self.status_code = status
        self.title = title

        self.json_detail = {
            "title": self.title,
            "detail": self.detail,
        }
        if self.ext:
            self.json_detail.update(self.ext)


def problem(status, title, detail, type=None, instance=None, headers=None, ext=None):
    return HttpResponse(content=detail, headers=headers, status=status)


class FlaskApi:
    @classmethod
    def get_response(self, _problem):
        return _problem


class ConnexionResponse(HttpResponse):
    def __init__(self, *args, **kwargs):
        if "status_code" in kwargs:
            kwargs["status"] = kwargs["status_code"]
            del kwargs["status_code"]
            super().__init__(*args, **kwargs)


celery = MagicMock()

phab = PhabricatorClient(
    settings.PHABRICATOR_URL,
    settings.PHABRICATOR_UNPRIVILEGED_API_KEY,
)

g = None
request = None
