from django.test import TestCase
from django.urls import reverse

from parsifal.apps.reviews.models import Review
from parsifal.apps.reviews.tests.factories import ReviewFactory


class RapidReviewViewsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory(review_type=Review.RAPID)
        cls.author = cls.review.author

    def setUp(self):
        self.client.force_login(self.author)

    def url(self, name, review=None):
        review = review or self.review
        return reverse(name, args=(review.author.username, review.name))

    def test_protocol(self):
        page = self.client.get(self.url("protocol"))
        self.assertContains(page, "Practical Context")
        self.assertContains(page, "Selection procedure")
        self.assertContains(page, "rapid review</span>", html=False)
        self.assertContains(page, "Rapid Review Checklist</a>", html=False)
        other = ReviewFactory(author=self.author)
        page = self.client.get(self.url("protocol", other))
        self.assertNotContains(page, "Practical Context")
        self.assertNotContains(page, "Rapid Review Checklist")

    def test_save_protocol_fields(self):
        save = reverse("reviews:planning:save_protocol_fields")
        response = self.client.post(
            save,
            {
                "review-id": self.review.pk,
                "demand": "practitioners",
                "practical_problem": "Flaky tests.",
                "started_on": "2026-11-02",
                "deadline": "2026-11-09",
                "synthesis_strategy": "Narrative",
                "title": "ignored: not a field of this form",
            },
        )
        self.assertEqual(200, response.status_code, response.content)
        self.review.refresh_from_db()
        self.assertEqual(
            ("Flaky tests.", "Narrative"), (self.review.practical_problem, self.review.synthesis_strategy)
        )
        response = self.client.post(save, {"review-id": self.review.pk, "deadline": "2026-11-01"})
        self.assertEqual(400, response.status_code)
        self.assertIn("deadline cannot come before", response.content.decode())

    def test_checklist(self):
        url = self.url("rapid_review_checklist")
        self.assertContains(self.client.get(url), "A single search source")
        response = self.client.post(
            url,
            {"applied-rr_single_source": "on", "notes-rr_single_source": "Scopus", "action": "draft"},
            follow=True,
        )
        self.assertContains(response, "1 threat was added to Reporting")
        self.assertEqual(["A single search source"], list(self.review.threats.values_list("title", flat=True)))
        self.client.post(url, {"action": "save"})  # every box unticked
        self.assertFalse(self.review.checklist_items.filter(applied=True).exists())
        other = ReviewFactory(author=self.author)
        self.assertEqual(404, self.client.get(self.url("rapid_review_checklist", other)).status_code)
