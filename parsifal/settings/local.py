# flake8: noqa

from .base import *

# ==============================================================================
# CORE SETTINGS
# ==============================================================================

# Debug tooling is optional: a venv built without requirements/local.txt must still run with these settings.
# (silk < 5 also needed pkg_resources, which modern setuptools no longer ships; local.txt pins silk 5.x.)
from importlib.util import find_spec  # noqa: E402

if find_spec("debug_toolbar"):
    INSTALLED_APPS += ["debug_toolbar"]
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")

if find_spec("silk") and find_spec("pkg_resources"):
    INSTALLED_APPS += ["silk"]
    MIDDLEWARE.insert(0, "silk.middleware.SilkyMiddleware")


# ==============================================================================
# EMAIL SETTINGS
# ==============================================================================

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


# ==============================================================================
# THIRD-PARTY APPS
# ==============================================================================

SILKY_PYTHON_PROFILER = True
SILKY_PYTHON_PROFILER_BINARY = True
