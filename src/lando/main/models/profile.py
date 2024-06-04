from __future__ import annotations

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db import models

from lando.main.models.base import BaseModel

SCM_PERMISSIONS = (
    ("scm_conduit", "SCM_CONDUIT"),
    ("scm_level_1", "SCM_LEVEL_1"),
    ("scm_level_2", "SCM_LEVEL_2"),
    ("scm_level_3", "SCM_LEVEL_3"),
    ("scm_versioncontrol", "SCM_VERSIONCONTROL"),
)


class Profile(BaseModel):
    """A model to store additional information about users."""

    class Meta:
        permissions = SCM_PERMISSIONS

    user = models.OneToOneField(User, null=True, on_delete=models.SET_NULL)

    # User info fetched from SSO.
    userinfo = models.JSONField(default=dict, blank=True)

    def update_permissions(self):
        """Remove permissions (currently SCM) and re-add them based on userinfo."""
        self.user.user_permissions.remove(
            **[permission[0] for permission in SCM_PERMISSIONS]
        )

        groups = self.userinfo.get("https://sso.mozilla.com/claim/groups", [])
        content_type = ContentType.objects.get_for_model(self.__class__)

        for codename in SCM_PERMISSIONS:
            permission = Permission.objects.get(
                codename=codename,
                content_type=content_type,
            )
            if f"all_{permission}" in groups and f"expired_{permission}" not in groups:
                self.user.user_permissions.add(permission)
