from __future__ import annotations

from django.contrib.auth.models import User
from django.db import models

from lando.main.models.base import BaseModel


class Profile(BaseModel):
    user = models.OneToOneField(User, null=True, on_delete=models.SET_NULL)

    # Phabricator API token.
    phabricator_token = models.TextField(null=True, blank=True)

    # User info fetched from SSO.
    userinfo = models.JSONField(default=dict, blank=True)
