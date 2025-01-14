import enum
import logging
from typing import (
    Optional,
    Union,
)

from django.db import models
from django.utils.translation import gettext_lazy

from lando.main.models.base import BaseModel

logger = logging.getLogger(__name__)

ConfigurationValueType = Union[bool, int, str]


@enum.unique
class ConfigurationKey(enum.Enum):
    """Configuration keys used throughout the system."""

    LANDING_WORKER_PAUSED = "LANDING_WORKER_PAUSED"
    LANDING_WORKER_STOPPED = "LANDING_WORKER_STOPPED"
    API_IN_MAINTENANCE = "API_IN_MAINTENANCE"
    WORKER_THROTTLE_SECONDS = "WORKER_THROTTLE_SECONDS"
    AUTOMATION_WORKER_PAUSED = "AUTOMATION_WORKER_PAUSED"
    AUTOMATION_WORKER_STOPPED = "AUTOMATION_WORKER_STOPPED"


class VariableTypeChoices(models.TextChoices):
    """Types that will be used to determine what to parse string values into."""

    BOOL = "BOOL", gettext_lazy("Boolean")
    INT = "INT", gettext_lazy("Integer")
    STR = "STR", gettext_lazy("String")


class ConfigurationVariable(BaseModel):
    """An arbitrary key-value table store that can be used to configure the system."""

    key = models.TextField(unique=True)
    raw_value = models.TextField(default="", blank=True)

    variable_type = models.CharField(
        max_length=4,
        choices=VariableTypeChoices,
        default=VariableTypeChoices.STR,
        null=True,  # TODO: should change this to not-nullable
        blank=True,
    )

    @property
    def value(self) -> ConfigurationValueType:
        """The parsed value of `raw_value` based on `variable_type`.

        Returns:
            If `variable_type` is set to `VariableTypeChoices.BOOL`, then `raw_value` is
            checked against a list of "truthy" values and a boolean is returned. If it
            is set to `VariableTypeChoices.INT`, then `raw_value` is converted to an integer
            before being returned. Otherwise, if it is set to `VariableTypeChoices.STR`,
            `raw_value` is returned as the original string.

        Raises:
            `ValueError`: If `variable_type` is set to `INT`, but `raw_value` is not a
            string representing an integer.
        """
        if self.variable_type == VariableTypeChoices.BOOL:
            return self.raw_value.lower() in ("1", "true")
        elif self.variable_type == VariableTypeChoices.INT:
            try:
                return int(self.raw_value)
            except ValueError:
                logger.error(f"Could not convert {self.raw_value} to an integer.")
        elif self.variable_type == VariableTypeChoices.STR:
            return self.raw_value

        raise ValueError("Could not parse raw value for configuration variable.")

    @classmethod
    def get(
        cls, key: ConfigurationKey, default: ConfigurationValueType
    ) -> ConfigurationValueType:
        """Fetch a variable using `key`, return `default` if it does not exist.

        Returns: The parsed value of the configuration variable, of type `str`, `int`,
            or `bool`.
        """
        try:
            return cls.objects.get(key=key.value).value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set(
        cls,
        key: ConfigurationKey,
        variable_type: VariableTypeChoices,
        raw_value: ConfigurationValueType,
    ) -> Optional[ConfigurationValueType]:
        """Set a variable `key` of type `variable_type` and value `raw_value`.

        Returns:
            ConfigurationVariable: The configuration variable that was created and/or
                set.

        NOTE: This method will create the variable with the provided `key` if it does
        not exist.
        """
        try:
            record = cls.objects.get(key=key.value)
        except cls.DoesNotExist:
            record = None
        if (
            record
            and record.variable_type == variable_type
            and record.raw_value == raw_value
        ):
            logger.info(
                f"Configuration variable {key.value} is already set to {raw_value}."
            )
            return

        if not record:
            logger.info(f"Creating new configuration variable {key.value}.")
            record = cls()

        if record.raw_value:
            logger.info(
                f"Configuration variable {key.value} previously set to {record.raw_value} "
                f"({record.value})"
            )
        record.variable_type = variable_type
        record.key = key.value
        record.raw_value = raw_value
        logger.info(
            f"Configuration variable {key.value} set to {raw_value} ({record.value})"
        )
        record.save()
        return record
