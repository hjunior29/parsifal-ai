# flake8: noqa

from .base import *

# ==============================================================================
# SECURITY SETTINGS
# ==============================================================================

# Set PARSIFAL_HTTPS=True when the instance is served over HTTPS (directly or behind a reverse proxy that sets
# X-Forwarded-Proto). Plain HTTP on a trusted network keeps the defaults below off so cookies and redirects work.
PARSIFAL_HTTPS = config("PARSIFAL_HTTPS", default=False, cast=bool)

CSRF_COOKIE_SECURE = PARSIFAL_HTTPS
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = PARSIFAL_HTTPS

SECURE_SSL_REDIRECT = PARSIFAL_HTTPS
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7 * 52 if PARSIFAL_HTTPS else 0  # one year
SECURE_HSTS_INCLUDE_SUBDOMAINS = PARSIFAL_HTTPS
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())


# ==============================================================================
# EMAIL SETTINGS
# ==============================================================================

# Without an SMTP host, e-mails (password reset) are written to the console/log so the instance still
# works; the administrator can copy the links from the log.
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default=(
        "django.core.mail.backends.smtp.EmailBackend"
        if EMAIL_HOST
        else "django.core.mail.backends.console.EmailBackend"
    ),
)
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="Parsifal <noreply@localhost>")
SERVER_EMAIL = config("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
EMAIL_SUBJECT_PREFIX = "[Parsifal] "
