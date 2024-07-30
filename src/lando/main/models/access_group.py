from django.db import models

from lando.main.models.base import BaseModel


class AccessGroup(BaseModel):
    permission = models.CharField(max_length=255, unique=True)
    active_group = models.CharField(max_length=255)
    expired_group = models.CharField(max_length=255)
    membership_group = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)

    def __str__(self):
        return self.display_name
