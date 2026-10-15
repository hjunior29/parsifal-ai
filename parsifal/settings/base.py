from pathlib import Path

from django.utils.translation import gettext_lazy as _

import dj_database_url
from decouple import Csv, config

# ==============================================================================
# CORE SETTINGS
# ==============================================================================
import parsifal
from parsifal.apps.core.constants import Environments

BASE_DIR = Path(__file__).resolve(strict=True).parent.parent

# Writable directory holding the SQLite database, uploaded media and collected static files.
# Defaults to <repository root>/data so a self-hosted instance keeps all its state in one place.
PARSIFAL_DATA_DIR = Path(config("PARSIFAL_DATA_DIR", default=str(BASE_DIR.parent / "data")))
PARSIFAL_DATA_DIR.mkdir(parents=True, exist_ok=True)

SECRET_KEY = config("SECRET_KEY", default="parsifal.settings.local")

DEBUG = config("DEBUG", default=True, cast=bool)

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost", cast=Csv())

_csv_comma = Csv(post_process=tuple)
_csv_semicolon = Csv(delimiter=";")

ADMINS = [_csv_comma(admin) for admin in _csv_semicolon(config("ADMINS", default=""))]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.sitemaps",
    "django.contrib.humanize",
    "compressor",
    "crispy_forms",
    "ninja",
    "parsifal.api",
    "parsifal.apps.reviews",
    "parsifal.apps.reviews.planning",
    "parsifal.apps.reviews.conducting",
    "parsifal.apps.reviews.reporting",
    "parsifal.apps.reviews.settings",
    "parsifal.apps.accounts",
    "parsifal.apps.authentication",
    "parsifal.apps.core",
    "parsifal.apps.invites",
    "parsifal.apps.library",
]

INTERNAL_IPS = ["127.0.0.1"]

ROOT_URLCONF = "parsifal.urls"

WSGI_APPLICATION = "parsifal.wsgi.application"

SITE_ID = 1

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760


# ==============================================================================
# MIDDLEWARE SETTINGS
# ==============================================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ==============================================================================
# TEMPLATES SETTINGS
# ==============================================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(BASE_DIR / "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "parsifal.apps.core.context_processors.settings",
            ],
        },
    },
]

# ==============================================================================
# DATABASES SETTINGS
# ==============================================================================

DATABASES = {
    "default": dj_database_url.config(
        default=config("DATABASE_URL", default=f"sqlite:///{PARSIFAL_DATA_DIR / 'parsifal.sqlite3'}"),
        conn_max_age=600,
    )
}

# ==============================================================================
# AUTHENTICATION AND AUTHORIZATION SETTINGS
# ==============================================================================

AUTHENTICATION_BACKENDS = ("parsifal.apps.authentication.backends.CaseInsensitiveUsernameOrEmailModelBackend",)

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

ABSOLUTE_URL_OVERRIDES = {
    "auth.user": lambda u: "/%s/" % u.username,
}

LOGIN_REDIRECT_URL = "login_redirect"
LOGOUT_REDIRECT_URL = "home"
LOGIN_URL = "login"
LOGOUT_URL = "logout"


# ==============================================================================
# INTERNATIONALIZATION AND LOCALIZATION SETTINGS
# ==============================================================================

LANGUAGE_CODE = config("LANGUAGE_CODE", default="en-us")

TIME_ZONE = config("TIME_ZONE", default="UTC")

USE_I18N = True

USE_L10N = True

USE_TZ = True

LANGUAGES = (("en-us", _("English")), ("pt-br", _("Brazilian Portuguese")))

LOCALE_PATHS = [str(BASE_DIR / "locale")]


# ==============================================================================
# STATIC FILES SETTINGS
# ==============================================================================

STATIC_URL = "/static/"
STATIC_ROOT = PARSIFAL_DATA_DIR / "static"
STATICFILES_DIRS = [str(BASE_DIR / "static")]
STATICFILES_FINDERS = (
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
    "compressor.finders.CompressorFinder",
)


# ==============================================================================
# MEDIA FILES SETTINGS
# ==============================================================================

MEDIA_URL = "/media/"
MEDIA_ROOT = PARSIFAL_DATA_DIR / "media"
DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"


# ==============================================================================
# THIRD-PARTY APPS
# ==============================================================================

COMPRESS_ENABLED = config("COMPRESS_ENABLED", default=not DEBUG, cast=bool)

CRISPY_TEMPLATE_PACK = "bootstrap3"

NINJA_PAGINATION_PER_PAGE = 100
NINJA_PAGINATION_MAX_LIMIT = 1000

ELSEVIER_API_KEY = config("ELSEVIER_API_KEY", default="")

# ==============================================================================
# FIRST-PARTY APP
# ==============================================================================

PARSIFAL_RELEASE = f"parsifal@{parsifal.__version__}"
PARSIFAL_ENVIRONMENT = config("PARSIFAL_ENVIRONMENT", default=Environments.LOCAL)

# Self-hosted instances are closed by default: accounts are created by the administrator or through
# co-author invites. Set to True to let anyone register.
PARSIFAL_ALLOW_SIGNUP = config("PARSIFAL_ALLOW_SIGNUP", default=False, cast=bool)
