# flake8: noqa

import tempfile
from pathlib import Path

from .base import *

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# WhiteNoise would otherwise warn that the collected static directory does not exist in the test environment.
WHITENOISE_AUTOREFRESH = True

# Uploaded files go to a throwaway folder, never to the data directory of a real instance.
STORAGES["files"] = {
    "BACKEND": "django.core.files.storage.FileSystemStorage",
    "OPTIONS": {"location": str(Path(tempfile.gettempdir()) / "parsifal-test-files")},
}

# Requests to Jev are mocked in tests: no spacing, so that the retries' waits are the only ones.
JEV_REQUESTS_PER_MINUTE = 0
