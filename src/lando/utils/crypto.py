from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings

ENCRYPTED_FIELD_PREFIX = "encrypted_"
CLEAR_FIELD_PREFIX = "clear_"
SET_FIELD_PREFIX = "set_"
ROTATE_FIELD_PREFIX = "rotate_"
FUNC_PREFIXES = (
    CLEAR_FIELD_PREFIX,
    SET_FIELD_PREFIX,
    ROTATE_FIELD_PREFIX,
)

# Provide encryption/decryption functionality.
cryptography = MultiFernet([Fernet(key) for key in settings.ENCRYPTION_KEYS])
