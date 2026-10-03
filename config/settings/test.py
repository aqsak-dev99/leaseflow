import tempfile
from pathlib import Path

from .dev import *  # noqa: F403

# Tests do not need slow, secure password hashing.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Files created while testing go to a throwaway folder, never the real media folder.
MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="leaseflow-test-media-"))
