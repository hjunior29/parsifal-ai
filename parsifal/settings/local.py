# flake8: noqa

# Debug tooling is optional: a venv built without requirements/local.txt must still run with these settings.
# (silk < 5 also needed pkg_resources, which modern setuptools no longer ships; local.txt pins silk 5.x.)
from importlib.util import find_spec  # noqa: E402

from decouple import config

from .base import *

# ==============================================================================
# CORE SETTINGS
# ==============================================================================


if find_spec("debug_toolbar"):
    INSTALLED_APPS += ["debug_toolbar"]
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")

# silk writes every request, SQL query and profile into the main SQLite database, which grows by hundreds of MB and
# competes with real writes ("database is locked" during imports). Opt in only while profiling: SILK=1.
if config("SILK", default=False, cast=bool) and find_spec("silk"):
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
