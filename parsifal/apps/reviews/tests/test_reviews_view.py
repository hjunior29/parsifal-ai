from django.test.testcases import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.tests.factories import ReviewFactory


class TestReviewsView(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory(title="TEST_REVIEW")
        cls.url = reverse("reviews", args=(cls.review.author.username,))

    def test_login_required(self):
        response = self.client.get(self.url)
        self.assertEqual(302, response.status_code)

    def test_own_page_lists_reviews(self):
        self.client.force_login(self.review.author)
        response = self.client.get(self.url)
        with self.subTest(msg="Test get status code"):
            self.assertEqual(200, response.status_code)
        with self.subTest(msg="Test review visible to author"):
            self.assertContains(response, self.review.title)
        with self.subTest(msg="Test review type column"):
            self.assertContains(response, "Literature review")

    def test_other_users_pages_do_not_exist(self):
        """No public profiles: another user's page is a 404 (not even its existence is revealed)."""
        user = UserFactory()
        self.client.force_login(user)
        self.assertEqual(404, self.client.get(self.url).status_code)
