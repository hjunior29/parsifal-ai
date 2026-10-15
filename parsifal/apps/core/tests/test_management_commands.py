import io

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.reviews.models import Source


class TestLoadDefaultSources(TestCase):
    def test_idempotent(self):
        call_command("load_default_sources", stdout=io.StringIO())
        call_command("load_default_sources", stdout=io.StringIO())
        self.assertEqual(7, Source.objects.filter(is_default=True).count())
        self.assertTrue(Source.objects.filter(name="Scopus", is_default=True).exists())


class TestCreateApiToken(TestCase):
    def test_prints_key(self):
        user = User.objects.create_user("alice", "alice@example.com", "pw")
        out, err = io.StringIO(), io.StringIO()
        call_command("create_api_token", user="ALICE", name="agent", stdout=out, stderr=err)
        key = out.getvalue().strip()
        self.assertEqual(user, ApiToken.objects.authenticate(key))
        self.assertIn("cannot be shown again", err.getvalue())

    def test_unknown_user(self):
        with self.assertRaises(CommandError):
            call_command("create_api_token", user="nobody", stdout=io.StringIO())


class TestInit(TestCase):
    def test_bootstraps_instance(self):
        out = io.StringIO()
        call_command("init", username="boss", email="boss@example.com", password="S3cret!!", token="first", stdout=out)
        output = out.getvalue()
        admin = User.objects.get(username="boss")
        with self.subTest(msg="admin created"):
            self.assertTrue(admin.is_superuser and admin.check_password("S3cret!!"))
        with self.subTest(msg="sources loaded"):
            self.assertEqual(7, Source.objects.filter(is_default=True).count())
        with self.subTest(msg="token printed"):
            key = output.split("API token 'first': ")[1].split()[0]
            self.assertEqual(admin, ApiToken.objects.authenticate(key))
        with self.subTest(msg="re-running keeps the admin"):
            out = io.StringIO()
            call_command("init", username="boss", stdout=out)
            self.assertIn("already exists", out.getvalue())
            self.assertEqual(1, User.objects.filter(is_superuser=True).count())

    def test_generated_password_is_printed(self):
        out = io.StringIO()
        call_command("init", username="auto", stdout=out)
        self.assertIn("Generated password for 'auto'", out.getvalue())

    def test_existing_non_admin_user_is_refused(self):
        User.objects.create_user("plain", "plain@example.com", "pw")
        with self.assertRaises(CommandError):
            call_command("init", username="plain", stdout=io.StringIO())
