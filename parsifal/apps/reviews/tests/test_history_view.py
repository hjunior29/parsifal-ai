from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.models import ReviewEvent
from parsifal.apps.reviews.services import history
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory


class HistoryViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserFactory(username="owner")
        cls.colleague = UserFactory(username="colleague")
        cls.review = ReviewFactory(author=cls.owner, co_authors=[cls.colleague], title="Agents")
        cls.url = reverse("review_history", args=(cls.owner.username, cls.review.name))
        cls.study = ArticleFactory(review=cls.review, title="A study")
        with history.acting(cls.owner, ReviewEvent.WEB):
            history.record(
                cls.review,
                ReviewEvent.PLANNING,
                history.CHANGED,
                "Changed the protocol (Objective)",
                changes=[history.change("Objective", "Why", "Why not")],
            )
        with history.acting(cls.colleague, ReviewEvent.CLI):
            history.record(
                cls.review, ReviewEvent.SELECTION, history.CHANGED, "Accepted a study", articles=[cls.study]
            )

    def test_members_only(self):
        self.assertEqual(404, self.client.get(self.url).status_code)  # like the review's other pages
        self.client.force_login(UserFactory())
        self.assertEqual(404, self.client.get(self.url).status_code)
        self.client.force_login(self.colleague)
        response = self.client.get(self.url)
        self.assertEqual(200, response.status_code)
        self.assertContains(response, f'href="{self.url}">History</a>')

    def test_every_change_with_its_details(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertContains(response, "Changed the protocol (Objective)")
        self.assertContains(response, "Why not")
        self.assertContains(response, "amendment")
        self.assertContains(response, "Accepted a study")
        self.assertContains(response, f'href="?study={self.study.pk}"')
        self.assertContains(
            response, "<strong>1</strong>–<strong>2</strong> of <strong>2</strong> changes", html=False
        )

    def test_filters(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url, {"actor": "colleague", "via": "cli"})
        self.assertContains(response, "Accepted a study")
        self.assertNotContains(response, "Changed the protocol (Objective)")
        response = self.client.get(self.url, {"study": self.study.pk})
        self.assertContains(response, "The changes to the study <strong>A study</strong>")
        self.assertNotContains(response, "Changed the protocol (Objective)")
        response = self.client.get(self.url, {"area": "nowhere"})
        self.assertContains(response, "area must be one of")
        response = self.client.get(self.url, {"q": "nothing like it"})
        self.assertContains(response, "No change matches the filters.")

    def test_an_empty_history(self):
        review = ReviewFactory(author=self.owner)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("review_history", args=(self.owner.username, review.name)))
        self.assertContains(response, "No change was recorded yet.")


class WebChangesTest(TestCase):
    """The review's own pages record what they change, as their user's, through the web."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = UserFactory(username="owner")
        cls.colleague = UserFactory(username="colleague")
        cls.review = ReviewFactory(author=cls.owner, co_authors=[cls.colleague], title="Agents")

    def latest(self):
        return self.review.events.order_by("pk").last()

    def test_details_and_settings(self):
        self.client.force_login(self.owner)
        self.client.post(
            reverse("review", args=(self.owner.username, self.review.name)),
            {"title": "AI agents", "description": ""},
        )
        event = self.latest()
        self.assertEqual(
            ("Changed the review details (Title)", self.owner, ReviewEvent.WEB),
            (event.summary, event.actor, event.via),
        )
        self.assertEqual([{"key": "title", "field": "Title", "before": "Agents", "after": "AI agents"}], event.changes)
        self.client.post(
            reverse("settings", args=(self.owner.username, self.review.name)),
            {"name": "ai-agents", "review_type": "mapping"},
        )
        self.assertEqual("Changed the review details (Name, Review type)", self.latest().summary)

    def test_new_review(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("reviews:new"), {"title": "Smart glasses", "description": "", "review_type": "slr"})
        event = ReviewEvent.objects.order_by("pk").last()
        self.assertEqual(("Created the review “Smart glasses”", self.owner), (event.summary, event.actor))

    def test_co_authors(self):
        self.client.force_login(self.colleague)
        self.client.post(reverse("reviews:leave"), {"review-id": self.review.pk})
        event = self.latest()
        self.assertEqual(("Left the review", self.colleague), (event.summary, event.actor))
        self.review.co_authors.add(self.colleague)
        self.client.force_login(self.owner)
        self.client.post(
            reverse("reviews:remove_author_from_review"), {"review-id": self.review.pk, "user-id": self.colleague.pk}
        )
        self.assertEqual(f"Removed the co-author “{self.colleague.username}”", self.latest().summary)
