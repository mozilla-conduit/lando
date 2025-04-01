from django.core.files.storage import storages
from django.http import HttpResponse
from storages.backends.gcloud import GoogleCloudStorage


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


def problem(  # noqa: ANN201
    status,  # noqa: ANN001
    title,  # noqa: ANN001
    detail,  # noqa: ANN001
    type=None,  # noqa: ANN001
    instance=None,  # noqa: ANN001
    headers=None,  # noqa: ANN001
    ext=None,  # noqa: ANN001
):
    return HttpResponse(content=detail, headers=headers, status=status)


request = {
    "headers": {},
}

session = {}


g = None


class FlaskApi:
    @classmethod
    def get_response(self, _problem):  # noqa: ANN001, ANN206
        return _problem


class ConnexionResponse(HttpResponse):
    def __init__(self, *args, **kwargs):
        if "status_code" in kwargs:
            kwargs["status"] = kwargs["status_code"]
            del kwargs["status_code"]
            super().__init__(*args, **kwargs)
