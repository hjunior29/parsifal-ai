from django.contrib.auth.models import User
from django.test import override_settings
from django.test.testcases import TestCase
from django.urls import reverse

from parsifal.apps.invites.constants import InviteStatus
from parsifal.apps.invites.tests.factories import InviteFactory

SIGNUP_DATA = {
    "username": "jane",
    "email": "jane.doe@example.com",
    "password1": "S3cr3tPass",
    "password2": "S3cr3tPass",
}


@override_settings(PARSIFAL_ALLOW_SIGNUP=True)
class TestSignUpView(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("signup")

    def test_get_success(self):
        response = self.client.get(self.url)
        with self.subTest(msg="Test get status code"):
            self.assertEqual(200, response.status_code)

        parts = ("csrfmiddlewaretoken", "username", "email", "password1", "password2")
        for part in parts:
            with self.subTest(msg="Test response body", part=part):
                self.assertContains(response, part)

    def test_post_success(self):
        response = self.client.post(self.url, SIGNUP_DATA, follow=True)

        with self.subTest(msg="Test post status code"):
            self.assertEqual(302, response.redirect_chain[0][1])

        with self.subTest(msg="Test post redirect status code"):
            self.assertEqual(200, response.status_code)

        with self.subTest(msg="Test user authenticated after sign up"):
            self.assertTrue(response.context["user"].is_authenticated)

        with self.subTest(msg="Test success message"):
            self.assertContains(response, "Your account was successfully created.")

        with self.subTest(msg="Test user created"):
            self.assertTrue(User.objects.filter(username="jane").exists())

    def test_post_fail(self):
        data = dict(SIGNUP_DATA, password1="123", password2="321")
        response = self.client.post(self.url, data)

        with self.subTest(msg="Test post status code"):
            self.assertEqual(200, response.status_code)

        with self.subTest(msg="Test error message"):
            self.assertContains(response, "There were some problems while creating your account.")

        with self.subTest(msg="Test user not created"):
            self.assertFalse(User.objects.filter(username="jane").exists())


@override_settings(PARSIFAL_ALLOW_SIGNUP=False)
class TestSignUpDisabled(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.url = reverse("signup")

    def test_get_forbidden(self):
        response = self.client.get(self.url)
        self.assertEqual(403, response.status_code)

    def test_post_forbidden(self):
        response = self.client.post(self.url, SIGNUP_DATA)
        with self.subTest(msg="Test post status code"):
            self.assertEqual(403, response.status_code)
        with self.subTest(msg="Test user not created"):
            self.assertFalse(User.objects.filter(username="jane").exists())

    def test_header_hides_sign_up_button(self):
        response = self.client.get(reverse("login"))
        self.assertNotContains(response, reverse("signup"))

    def test_pending_invite_still_allows_sign_up(self):
        invite = InviteFactory(invitee=None, invitee_email="jane.doe@example.com")

        with self.subTest(msg="Test get with invite code"):
            response = self.client.get(self.url, {"invite": invite.code})
            self.assertEqual(200, response.status_code)

        data = dict(SIGNUP_DATA, invite=invite.pk)
        response = self.client.post(f"{self.url}?invite={invite.code}", data, follow=True)
        invite.refresh_from_db()

        with self.subTest(msg="Test user created and logged in"):
            self.assertEqual(200, response.status_code)
            self.assertTrue(User.objects.filter(username="jane").exists())

        with self.subTest(msg="Test invite accepted and user added as co-author"):
            self.assertEqual(InviteStatus.ACCEPTED, invite.status)
            self.assertTrue(invite.review.is_author_or_coauthor(User.objects.get(username="jane")))

    def test_invalid_invite_code_forbidden(self):
        response = self.client.get(self.url, {"invite": "not-a-uuid"})
        self.assertEqual(403, response.status_code)
