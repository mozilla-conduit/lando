from django.core.files.storage import storages
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
