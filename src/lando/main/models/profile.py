from __future__ import annotations

from django.contrib.auth.models import User
from django.db import models

from lando.main.models.base import BaseModel


class Profile(BaseModel):
    """A model to store additional information about users."""

    user = models.OneToOneField(User, null=True, on_delete=models.SET_NULL)

    # User info fetched from SSO.
    userinfo = models.JSONField(default=dict, blank=True)
