from __future__ import annotations

from cryptography.fernet import Fernet
from django.conf import settings
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

SCM_PERMISSIONS_MAP = {value: f"main.{key}" for key, value in SCM_PERMISSIONS}

SCM_ALLOW_DIRECT_PUSH = SCM_PERMISSIONS_MAP["SCM_ALLOW_DIRECT_PUSH"]
SCM_CONDUIT = SCM_PERMISSIONS_MAP["SCM_CONDUIT"]
SCM_FIREFOXCI = SCM_PERMISSIONS_MAP["SCM_FIREFOXCI"]
SCM_L10N_INFRA = SCM_PERMISSIONS_MAP["SCM_L10N_INFRA"]
SCM_LEVEL_1 = SCM_PERMISSIONS_MAP["SCM_LEVEL_1"]
SCM_LEVEL_2 = SCM_PERMISSIONS_MAP["SCM_LEVEL_2"]
SCM_LEVEL_3 = SCM_PERMISSIONS_MAP["SCM_LEVEL_3"]
SCM_NSS = SCM_PERMISSIONS_MAP["SCM_NSS"]
SCM_VERSIONCONTROL = SCM_PERMISSIONS_MAP["SCM_VERSIONCONTROL"]


def filter_claims(claims: dict) -> dict:
    """Return only necessary info in the provided dict."""
    keep_keys = (
        "email",
        "email_verified",
        "name",
        "picture",
        CLAIM_GROUPS_KEY,
    )

    # Remove keys that are not present in keep_keys.
    claims = {key: value for key, value in claims.items() if key in keep_keys}

    # Remove reference to any groups not currently used in Lando.
    # NOTE: currently these are SCM group, however in the future other
    # groups will need to be added here, for example "treestatus users",
    # and other lando permissions.
    # This filter is only applicable to remote environments at this time.
    if settings.ENVIRONMENT.is_remote:
        claims[CLAIM_GROUPS_KEY] = [
            group for group in claims[CLAIM_GROUPS_KEY] if "scm" in group.lower()
        ]
    return claims


class Profile(BaseModel):
    """A model to store additional information about users."""

    class Meta:
        permissions = SCM_PERMISSIONS

    # Provide encryption/decryption functionality.
    cryptography = Fernet(settings.ENCRYPTION_KEY)

    user = models.OneToOneField(User, null=True, on_delete=models.SET_NULL)

    # User info fetched from SSO.
    userinfo = models.JSONField(default=dict, blank=True)

    # Encrypted Phabricator API token.
    encrypted_phabricator_api_key = models.BinaryField(default=b"", blank=True)

    # Encrypted API key.
    encrypted_lando_api_key = models.BinaryField(default=b"", blank=True)

    def _encrypt_value(self, value: str) -> bytes:
        """Encrypt a given string value."""
        return self.cryptography.encrypt(value.encode("utf-8"))

    def _decrypt_value(self, value: bytes) -> str:
        """Decrypt a given bytes value."""
        return self.cryptography.decrypt(value).decode("utf-8")

    def _has_scm_permission_groups(self, codename: str, groups: list[str]) -> bool:
        """Return whether the group membership provides the correct permission.

        In order to have a particular SCM permission, both the "active" and "all" groups
        need to exist, and the "expired" group should not exist.
        """
        return {f"all_{codename}", f"active_{codename}"}.issubset(
            groups
        ) and f"expired_{codename}" not in groups

    @classmethod
    def get_all_scm_permissions(cls) -> dict[str, Permission]:
        """Return all SCM permission objects in the system."""
        content_type = ContentType.objects.get_for_model(cls)

        permissions = {
            codename: Permission.objects.get(
                codename=codename, content_type=content_type
            )
            for codename, name in SCM_PERMISSIONS
        }

        return permissions

    @property
    def phabricator_api_key(self) -> str:
        """Decrypt and return the value of the Phabricator API key."""
        encrypted_key = bytes(self.encrypted_phabricator_api_key)
        if encrypted_key:
            return self._decrypt_value(encrypted_key)
        else:
            return ""

    def clear_phabricator_api_key(self):
        """Set the phabricator API key to an empty string and save."""
        self.save_phabricator_api_key("")

    def save_phabricator_api_key(self, key: str):
        """Given a raw API key, encrypt it and store it in the relevant field."""
        self.encrypted_phabricator_api_key = self._encrypt_value(key)
        self.save()

    @property
    def lando_api_key(self) -> str:
        """Decrypt and return the value of the Lando API key."""
        encrypted_key = bytes(self.encrypted_lando_api_key)
        if encrypted_key:
            return self._decrypt_value(encrypted_key)

        return ""

    def clear_lando_api_key(self):
        """Set the Lando API key to an empty string and save."""
        self.save_lando_api_key("")

    def save_lando_api_key(self, key: str):
        """Given a raw Lando API key, encrypt it and store it in the relevant field."""
        self.encrypted_lando_api_key = self._encrypt_value(key)
        self.save()

    def update_permissions(self):
        """Remove SCM permissions and re-add them based on userinfo."""
        permissions = self.get_all_scm_permissions()
        self.user.user_permissions.remove(*permissions.values())
        groups = self.userinfo.get(CLAIM_GROUPS_KEY, [])
        for codename in permissions:
            if self._has_scm_permission_groups(codename, groups):
                self.user.user_permissions.add(permissions[codename])
