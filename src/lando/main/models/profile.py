from __future__ import annotations

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db import models

from lando.main.models.base import BaseModel

SCM_PERMISSIONS = (
    ("scm_allow_direct_push", "SCM_ALLOW_DIRECT_PUSH"),
    ("scm_conduit", "SCM_CONDUIT"),
    ("scm_firefoxci", "SCM_FIREFOXCI"),
    ("scm_l10n_infra", "SCM_L10N_INFRA"),
    ("scm_level_1", "SCM_LEVEL_1"),
    ("scm_level_2", "SCM_LEVEL_2"),
    ("scm_level_3", "SCM_LEVEL_3"),
    ("scm_nss", "SCM_NSS"),
    ("scm_versioncontrol", "SCM_VERSIONCONTROL"),
)

CLAIM_GROUPS_KEY = "https://sso.mozilla.com/claim/groups"


class Profile(BaseModel):
    """A model to store additional information about users."""

    class Meta:
        permissions = SCM_PERMISSIONS

    user = models.OneToOneField(User, null=True, on_delete=models.SET_NULL)

    # User info fetched from SSO.
    userinfo = models.JSONField(default=dict, blank=True)

    def update_permissions(self):
        """Remove SCM permissions and re-add them based on userinfo."""
        content_type = ContentType.objects.get_for_model(self.__class__)

        permissions = {
            codename: Permission.objects.get(
                codename=codename, content_type=content_type
            )
            for codename, name in SCM_PERMISSIONS
        }

        self.user.user_permissions.remove(*permissions.values())

        groups = self.userinfo.get(CLAIM_GROUPS_KEY, [])

        for codename in permissions:
            if (
                set(groups).intersection((f"all_{codename}", f"active_{codename}"))
                and f"expired_{codename}" not in groups
            ):
                self.user.user_permissions.add(permissions[codename])
