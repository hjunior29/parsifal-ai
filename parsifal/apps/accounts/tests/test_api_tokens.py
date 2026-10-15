from django.test import TestCase
from django.urls import reverse

from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.utils.test import login_redirect_url


class TestApiTokenModel(TestCase):
    def test_create_authenticate_revoke(self):
        user = UserFactory()
        token, raw_key = ApiToken.create_for(user, "CLI")
        with self.subTest(msg="raw key never stored"):
            self.assertTrue(raw_key.startswith("pfl_"))
            self.assertNotEqual(raw_key, token.key_hash)
            self.assertEqual(raw_key[:12], token.prefix)
        with self.subTest(msg="authenticate"):
            self.assertEqual(user, ApiToken.objects.authenticate(raw_key))
            self.assertIsNone(ApiToken.objects.authenticate("pfl_wrong"))
            self.assertIsNone(ApiToken.objects.authenticate(""))
            self.assertIsNone(ApiToken.objects.authenticate(None))
        with self.subTest(msg="revoke"):
            token.revoke()
            self.assertFalse(token.is_active)
            self.assertIsNone(ApiToken.objects.authenticate(raw_key))


class TestApiTokenViews(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.other = UserFactory()
        cls.url = reverse("settings:tokens")

    def test_login_required(self):
        self.assertRedirects(self.client.get(self.url), login_redirect_url(self.url))

    def test_create_shows_key_once_and_revoke(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"name": "Claude Code"})
        self.assertEqual(200, response.status_code)
        key = response.context["new_token_key"]
        self.assertContains(response, key)
        self.assertContains(response, "Copy this token now")

        with self.subTest(msg="key not shown on later visits"):
            response = self.client.get(self.url)
            self.assertNotContains(response, key)
            self.assertContains(response, "Claude Code")

        token = self.user.api_tokens.get()
        with self.subTest(msg="cannot revoke someone else's token"):
            other_token, _ = ApiToken.create_for(self.other, "x")
            response = self.client.post(reverse("settings:token_revoke", args=(other_token.pk,)))
            self.assertEqual(404, response.status_code)
        with self.subTest(msg="revoke own token"):
            response = self.client.post(reverse("settings:token_revoke", args=(token.pk,)), follow=True)
            self.assertContains(response, "was revoked")
            token.refresh_from_db()
            self.assertFalse(token.is_active)

    def test_blank_name_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"name": ""})
        self.assertContains(response, "This field is required.")
        self.assertFalse(self.user.api_tokens.exists())
