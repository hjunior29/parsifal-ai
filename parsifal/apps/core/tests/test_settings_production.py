import importlib
import os
from unittest import mock

from django.test import SimpleTestCase


def load_production(**env):
    """Import the production settings module with a controlled environment (python-decouple reads os.environ)."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("EMAIL_", "PARSIFAL_HTTPS", "CSRF_TRUSTED"))}
    clean.update(env)
    with mock.patch.dict(os.environ, clean, clear=True):
        import parsifal.settings.production as production

        return importlib.reload(production)


class TestProductionSettings(SimpleTestCase):
    def test_works_without_email_or_https_configuration(self):
        settings = load_production(SECRET_KEY="x")
        self.assertFalse(settings.SECURE_SSL_REDIRECT)
        self.assertFalse(settings.SESSION_COOKIE_SECURE)
        self.assertEqual(0, settings.SECURE_HSTS_SECONDS)
        self.assertEqual("django.core.mail.backends.console.EmailBackend", settings.EMAIL_BACKEND)
        self.assertIn("whitenoise.middleware.WhiteNoiseMiddleware", settings.MIDDLEWARE)

    def test_https_switch_and_smtp(self):
        settings = load_production(
            SECRET_KEY="x",
            PARSIFAL_HTTPS="True",
            EMAIL_HOST="smtp.example.org",
            CSRF_TRUSTED_ORIGINS="https://a.org,https://b.org",
        )
        self.assertTrue(
            settings.SECURE_SSL_REDIRECT and settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE
        )
        self.assertGreater(settings.SECURE_HSTS_SECONDS, 0)
        self.assertEqual("django.core.mail.backends.smtp.EmailBackend", settings.EMAIL_BACKEND)
        self.assertEqual(["https://a.org", "https://b.org"], settings.CSRF_TRUSTED_ORIGINS)
