from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.models import ReviewEvent
from parsifal.apps.reviews.services import threats
from parsifal.apps.reviews.tests.factories import ReviewFactory


class ThreatsViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserFactory(username="owner")
        cls.colleague = UserFactory(username="colleague")
        cls.review = ReviewFactory(author=cls.owner, co_authors=[cls.colleague])
        cls.url = reverse("threats_to_validity", args=(cls.owner.username, cls.review.name))

    def setUp(self):
        self.client.force_login(self.colleague)

    def test_members_only_and_reporting_opens_on_it(self):
        self.client.logout()
        self.assertEqual(404, self.client.get(self.url).status_code)
        self.client.force_login(UserFactory())
        self.assertEqual(404, self.client.get(self.url).status_code)
        self.client.force_login(self.colleague)
        reporting = reverse("reporting", args=(self.owner.username, self.review.name))
        self.assertRedirects(self.client.get(reporting), self.url)
        response = self.client.get(self.url)
        self.assertContains(response, "This review has no threats to validity yet.")
        self.assertContains(response, '<option value="Theoretical validity">', html=False)

    def test_add_edit_remove(self):
        response = self.client.post(
            self.url,
            {
                "action": "add",
                "title": "One reviewer",
                "category": "Theoretical validity",
                "description": "Studies may have been missed.",
                "mitigation": "",
            },
            follow=True,
        )
        self.assertContains(response, "The threat was added.")
        threat = self.review.threats.get()
        self.assertContains(response, "One reviewer")
        self.assertContains(response, "none written yet")
        self.assertEqual(
            (self.colleague, ReviewEvent.WEB), (self.review.events.get().actor, self.review.events.get().via)
        )
        response = self.client.get(self.url, {"edit": threat.pk})
        self.assertContains(response, 'value="update"', html=False)
        self.client.post(
            self.url,
            {
                "action": "update",
                "threat-id": threat.pk,
                "title": "One reviewer",
                "category": "Theoretical validity",
                "description": "Studies may have been missed.",
                "mitigation": "A test set of known studies.",
            },
        )
        threat.refresh_from_db()
        self.assertEqual("A test set of known studies.", threat.mitigation)
        response = self.client.post(self.url, {"action": "add", "title": ""}, follow=True)
        self.assertContains(response, "title is required.")
        self.client.post(self.url, {"action": "remove", "threat-id": threat.pk})
        self.assertFalse(self.review.threats.exists())

    def test_someone_elses_threat(self):
        other = threats.add_threat(review=ReviewFactory(), title="Theirs")
        response = self.client.post(self.url, {"action": "remove", "threat-id": other.pk}, follow=True)
        self.assertContains(response, "not found in this review")
        self.assertTrue(type(other).objects.filter(pk=other.pk).exists())
