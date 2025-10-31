import logging
from contextlib import ContextDecorator

from django.db import connection, models, transaction

logger = logging.getLogger(__name__)


class LockTableContextManager(ContextDecorator):
    """Decorator to lock table for current model."""

    def __init__(self, model, lock="SHARE ROW EXCLUSIVE"):  # noqa: ANN001
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


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    @classmethod
    @property
    def lock_table(cls):  # noqa: ANN206
        return LockTableContextManager(cls)

    @classmethod
    def one_or_none(cls, *args, **kwargs):  # noqa: ANN206
        try:
            result = cls.objects.get(*args, **kwargs)
        except cls.DoesNotExist:
            return None
        return result
