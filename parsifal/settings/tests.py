# flake8: noqa

from .base import *

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# WhiteNoise would otherwise warn that the collected static directory does not exist in the test environment.
WHITENOISE_AUTOREFRESH = True
