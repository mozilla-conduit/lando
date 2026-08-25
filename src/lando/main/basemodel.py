import logging
from contextlib import ContextDecorator
from typing import Callable

from django.db import connection, models, transaction

from lando.utils.crypto import ENCRYPTED_FIELD_PREFIX, FUNC_PREFIXES, cryptography

logger = logging.getLogger(__name__)


class LockTableContextManager(ContextDecorator):
    """Decorator to lock table for current model."""

    def __init__(self, model: models.Model, lock: str = "SHARE ROW EXCLUSIVE"):
        self.lock = lock
        self.model = model

        if lock not in ("SHARE ROW EXCLUSIVE",):
            raise ValueError(f"{lock} not valid.")

    def __enter__(self):
        cursor = connection.cursor()
        with transaction.atomic():
            cursor.execute(
                f"LOCK TABLE {self.model._meta.db_table} IN {self.lock} MODE"
            )

    def __exit__(self, exc_type, exc_value, traceback):  # noqa: ANN001
        pass


class CryptographyMixin:
    """
    Provide a more convenient way of encrypting and decrypting fields.

    String-based fields that are prefixed with `encrypted_` will have this feature enabled.
    For example, a field such as MyModel.encrypted_secret_name will provide the following:
    - MyModel.secret_name: The decrypted value of MyModel.encrypted_secret_name
    - MyModel.set_secret_name: Encrypt and set the value of MyModel.encrypted_secret_name
    - MyModel.clear_secret_name: Clear and encrypt the value of MyModel.encrypted_secret_name
    - MyModel.rotate_secret_name: Use when rotating the secret keys used to encrypt values.
    """

    def __getattr__(self, name: str) -> object:
        """Redirect to appropriate function call."""
        obj_dir = object.__dir__(self)
        encrypted_fields = tuple(
            field.removeprefix(ENCRYPTED_FIELD_PREFIX)
            for field in obj_dir
            if field.startswith(ENCRYPTED_FIELD_PREFIX)
        )
        crypto_methods = [
            f"{prefix}{field_name}"
            for prefix in FUNC_PREFIXES
            for field_name in encrypted_fields
        ]

        if name in crypto_methods:
            method, field_name = name.split("_", 1)
            return object.__getattribute__(self, f"get_{method}_encrypted_field")(
                field_name
            )

        if f"{ENCRYPTED_FIELD_PREFIX}{name}" in obj_dir:
            # The request is for the decrypted value of the field.
            return self._get_decrypted_value_or_empty(name)

        return object.__getattribute__(self, name)

    def _get_decrypted_value_or_empty(self, field_name: str) -> str:
        """Return decrypted value, or an empty string if there is no value."""
        encrypted_value = bytes(getattr(self, f"{ENCRYPTED_FIELD_PREFIX}{field_name}"))
        if encrypted_value:
            return self._decrypt_value(encrypted_value)
        else:
            return ""

    def _encrypt_value(self, value: str) -> bytes:
        """Encrypt a given string value."""
        return cryptography.encrypt(value.encode("utf-8"))

    def _decrypt_value(self, value: bytes) -> str:
        """Decrypt a given bytes value."""
        return cryptography.decrypt(value).decode("utf-8")

    def _rotate_value(self, value: bytes) -> bytes:
        """Return a rotated encrypted bytes value."""
        return cryptography.rotate(value)

    def get_clear_encrypted_field(self, field_name: str) -> Callable:
        """Return the corresponding method to clear the encrypted field."""
        set_encrypted_field = self.get_set_encrypted_field(field_name)

        def clear_encrypted_field(save: bool = True):
            """Set value to encrypted blank string."""
            set_encrypted_field("", save=save)

        return clear_encrypted_field

    def get_set_encrypted_field(self, field_name: str) -> Callable:
        """Return the corresponding method to set the encrypted field."""

        def set_encrypted_field(value: str, save: bool = True):
            """Set encrypted value to given field and save if needed."""
            setattr(
                self,
                f"{ENCRYPTED_FIELD_PREFIX}{field_name}",
                self._encrypt_value(value),
            )
            if save:
                self.save()

        return set_encrypted_field

    def get_rotate_encrypted_field(self, field_name: str) -> Callable:
        """Return the corresponding method to rotate the encrypted field."""

        def rotate_encrypted_field():
            """Rotate encryption on given field."""
            setattr(
                self,
                f"{ENCRYPTED_FIELD_PREFIX}{field_name}",
                self._rotate_value(
                    bytes(getattr(self, f"{ENCRYPTED_FIELD_PREFIX}{field_name}"))
                ),
            )
            self.save()

        return rotate_encrypted_field


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    @classmethod
    def lock_table(cls) -> LockTableContextManager:
        return LockTableContextManager(cls)

    @classmethod
    def one_or_none(cls, *args, **kwargs):  # noqa: ANN206
        try:
            result = cls.objects.get(*args, **kwargs)
        except cls.DoesNotExist:
            return None
        return result
