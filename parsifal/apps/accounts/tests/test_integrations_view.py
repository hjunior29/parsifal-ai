from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from parsifal.apps.accounts.models import Integration
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core import jev
from parsifal.utils.test import login_redirect_url

KEY = "fake-jev-key-0123456789abcdef"
MODELS = [
    {"name": "jev-1.13.0", "description": "Stable", "release_date": "2026-08-01"},
    {"name": "jev-1.14.0", "description": "Newest", "release_date": "2026-10-14"},
]


class TestIntegrationsView(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.other = UserFactory()
        cls.url = reverse("settings:integrations")

    def setUp(self):
        self.client.force_login(self.user)
        # The page asks Jev for its models on every load: never reach the network in tests.
        patcher = mock.patch.object(jev, "list_models", return_value=MODELS)
        self.list_models = patcher.start()
        self.addCleanup(patcher.stop)

    def test_login_required(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), login_redirect_url(self.url))

    def test_key_is_required_the_first_time(self):
        response = self.client.post(self.url, {"action": "save", "api_key": "  ", "model": "jev-1.13.0"})
        self.assertContains(response, "Paste the API key from your TypeSafe account.")
        self.assertFalse(Integration.objects.exists())

    def test_save_update_and_remove(self):
        response = self.client.get(self.url)
        self.assertContains(response, "not configured")
        self.assertContains(response, 'value="jev-1.13.0"')

        self.client.post(self.url, {"action": "save", "api_key": f" {KEY} ", "model": "jev-1.13.0"})
        integration = Integration.objects.get(user=self.user, provider=Integration.JEV)
        self.assertEqual((KEY, "jev-1.13.0"), (integration.api_key, integration.model))

        with self.subTest(msg="stored encrypted"):
            stored = Integration.objects.values_list("api_key_encrypted", "key_hint").get(pk=integration.pk)
            self.assertNotIn(KEY, stored[0])
            self.assertEqual("cdef", stored[1])

        with self.subTest(msg="the key is never rendered back"):
            response = self.client.get(self.url)
            self.assertNotContains(response, KEY)
            self.assertContains(response, "…cdef")
            self.assertContains(response, "Leave blank to keep the current key.")

        with self.subTest(msg="blank key keeps the saved one"):
            self.client.post(self.url, {"action": "save", "api_key": "", "model": "jev-1.14.0"})
            integration.refresh_from_db()
            self.assertEqual((KEY, "jev-1.14.0"), (integration.api_key, integration.model))

        with self.subTest(msg="a new key replaces it"):
            self.client.post(self.url, {"action": "save", "api_key": "fake-jev-key-new-9999", "model": "jev-1.14.0"})
            integration.refresh_from_db()
            self.assertEqual("fake-jev-key-new-9999", integration.api_key)

        with self.subTest(msg="other users do not see it"):
            self.client.force_login(self.other)
            self.assertContains(self.client.get(self.url), "not configured")
            self.client.post(self.url, {"action": "remove"})
            self.assertTrue(Integration.objects.filter(pk=integration.pk).exists())

        self.client.force_login(self.user)
        self.client.post(self.url, {"action": "remove"})
        self.assertFalse(Integration.objects.filter(user=self.user).exists())

    def test_test_the_key(self):
        response = self.client.post(self.url, {"action": "test"}, follow=True)
        self.assertContains(response, "Save an API key first.")

        Integration.objects.create(user=self.user, provider=Integration.JEV, api_key=KEY, model="jev-1.13.0")
        self.list_models.reset_mock()
        response = self.client.post(self.url, {"action": "test"}, follow=True)
        self.list_models.assert_any_call(KEY)
        self.assertContains(response, "Jev accepted the key. Models available: jev-1.13.0, jev-1.14.0.")

        error = jev.JevError("Jev rejected the API key. Update it in Settings → Integrations.", fatal=True)
        with mock.patch.object(jev, "list_models", side_effect=error):
            response = self.client.post(self.url, {"action": "test"}, follow=True)
        self.assertContains(response, "Jev rejected the API key.")

    def test_a_key_saved_under_another_secret_key_must_be_saved_again(self):
        with override_settings(SECRET_KEY="the-secret-key-before-rotation"):
            Integration.objects.create(user=self.user, provider=Integration.JEV, api_key=KEY, model="jev-1.13.0")
        response = self.client.post(self.url, {"action": "test"}, follow=True)
        self.assertContains(response, "can no longer be decrypted")

    def test_models_come_from_jev_on_every_load_and_the_default_is_saved(self):
        self.client.get(self.url)
        self.list_models.assert_not_called()  # no key yet: nothing to ask with
        self.client.post(self.url, {"action": "save", "api_key": KEY, "model": "jev-1.13.0"})

        self.list_models.reset_mock()
        response = self.client.get(self.url)
        self.list_models.assert_called_once_with(KEY)
        self.assertContains(
            response, '<option value="jev-1.14.0">jev-1.14.0 — Newest · 2026-10-14</option>', html=True
        )
        self.assertContains(
            response, '<option value="jev-1.13.0" selected>jev-1.13.0 — Stable · 2026-08-01</option>', html=True
        )

        self.client.post(self.url, {"action": "save", "api_key": "", "model": "jev-1.14.0"})
        self.assertEqual("jev-1.14.0", Integration.objects.get(user=self.user).model)
        response = self.client.post(self.url, {"action": "save", "api_key": "", "model": "jev-9"})
        self.assertContains(response, "Select a valid choice")

        with self.subTest(msg="a saved model Jev no longer lists stays selectable"):
            Integration.objects.filter(user=self.user).update(model="jev-1.12.0")
            response = self.client.get(self.url)
            self.assertContains(response, "jev-1.12.0 (not listed by Jev)")

        with self.subTest(msg="Jev unreachable: a warning and a text field"):
            self.list_models.side_effect = jev.JevError("Could not reach Jev (ConnectionError).")
            response = self.client.get(self.url)
            self.assertContains(response, "Could not load the list of models from Jev")
            self.assertContains(response, 'name="model" value="jev-1.12.0"')
