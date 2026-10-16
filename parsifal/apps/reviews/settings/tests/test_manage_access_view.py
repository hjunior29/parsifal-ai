from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.tests.factories import ReviewFactory
from parsifal.utils.test import login_redirect_url


class TestManageAccessView(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = UserFactory()
        cls.co_author = UserFactory()
        cls.other = UserFactory(username="newbie")
        cls.review = ReviewFactory(author=cls.author, co_authors=[cls.co_author])
        cls.url = reverse("manage_access", args=(cls.author.username, cls.review.name))

    def test_login_required(self):
        self.assertRedirects(self.client.get(self.url), login_redirect_url(self.url))

    def test_main_author_required(self):
        self.client.force_login(self.co_author)
        self.assertEqual(403, self.client.get(self.url).status_code)

    def test_get_lists_members(self):
        self.client.force_login(self.author)
        response = self.client.get(self.url)
        self.assertEqual(200, response.status_code)
        self.assertContains(response, self.co_author.username)
        self.assertContains(response, "Main author")

    def test_add_and_remove(self):
        self.client.force_login(self.author)
        response = self.client.post(self.url, {"action": "add", "username": "NEWBIE"}, follow=True)
        self.assertContains(response, "newbie is now a co-author.")
        self.assertTrue(self.review.is_author_or_coauthor(self.other))

        response = self.client.post(self.url, {"action": "add", "username": "newbie"}, follow=True)
        self.assertContains(response, "already a co-author")

        response = self.client.post(self.url, {"action": "add", "username": "ghost"}, follow=True)
        self.assertContains(response, "User not found.")

        response = self.client.post(self.url, {"action": "remove", "user_id": self.other.pk}, follow=True)
        self.assertContains(response, "newbie was removed from the review.")
        self.assertFalse(self.review.is_author_or_coauthor(self.other))
