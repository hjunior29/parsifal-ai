from django.test import TestCase

from parsifal.apps.core.exceptions import NotFound, ValidationError
from parsifal.apps.reviews.models import ReviewEvent
from parsifal.apps.reviews.services import threats
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory


class TestThreats(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory()

    def add(self, title, **fields):
        return threats.add_threat(review=self.review, title=title, **fields)

    def test_add_change_remove(self):
        threat = self.add(
            "  One reviewer  ",
            category="Theoretical validity",
            description="Studies may have been missed.",
            mitigation="A test set of known studies.",
        )
        self.assertEqual(
            ("One reviewer", "Theoretical validity", 0),
            (threat.title, threat.category, threat.order),
        )
        threat = threats.update_threat(review=self.review, threat_id=threat.pk, mitigation="A second reviewer")
        self.assertEqual(("One reviewer", "A second reviewer"), (threat.title, threat.mitigation))
        self.assertEqual(1, self.add("Another").order)
        threats.remove_threat(review=self.review, threat_id=threat.pk)
        self.assertEqual(["Another"], [t.title for t in threats.list_threats(self.review)])

    def test_any_type_and_the_rules(self):
        self.assertEqual("Our own type", self.add("A threat", category="Our own type").category)
        with self.assertRaises(ValidationError):
            self.add("  ")
        with self.assertRaises(ValidationError):
            self.add("x" * 256)
        with self.assertRaises(ValidationError):
            self.add("A threat", category="x" * 101)
        threat = self.add("Named")
        with self.assertRaises(ValidationError):
            threats.update_threat(review=self.review, threat_id=threat.pk, title="")
        with self.assertRaises(NotFound):
            threats.update_threat(review=ReviewFactory(), threat_id=threat.pk, title="Mine")

    def test_grouped_by_type_untyped_last(self):
        self.add("No type")
        self.add("Missed studies", category="Theoretical validity")
        self.add("Sample", category="Generalizability")
        self.add("Bias", category="Theoretical validity")
        self.assertEqual(
            [
                ("Theoretical validity", ["Missed studies", "Bias"]),
                ("Generalizability", ["Sample"]),
                ("", ["No type"]),
            ],
            [(category, [t.title for t in items]) for category, items in threats.grouped(self.review)],
        )

    def test_history_in_reporting_never_an_amendment(self):
        ArticleFactory(review=self.review)  # studies imported: still not a change to the protocol
        threat = self.add("One reviewer", category="Theoretical validity")
        threats.update_threat(review=self.review, threat_id=threat.pk, mitigation="A second reviewer")
        threats.update_threat(review=self.review, threat_id=threat.pk, mitigation="A second reviewer")  # nothing
        threats.remove_threat(review=self.review, threat_id=threat.pk)
        events = list(self.review.events.order_by("pk"))
        self.assertEqual(
            [
                ("add", "Added the threat to validity “One reviewer”"),
                ("change", "Changed the threat to validity “One reviewer”"),
                ("remove", "Removed the threat to validity “One reviewer”"),
            ],
            [(event.action, event.summary) for event in events],
        )
        self.assertEqual({ReviewEvent.REPORTING}, {event.area for event in events})
        self.assertEqual({False}, {event.amendment for event in events})
        self.assertEqual(
            [
                {"key": "title", "field": "Name", "before": "", "after": "One reviewer"},
                {"key": "category", "field": "Type", "before": "", "after": "Theoretical validity"},
            ],
            events[0].changes,
        )
        self.assertEqual(
            [{"key": "mitigation", "field": "Mitigation", "before": "", "after": "A second reviewer"}],
            events[1].changes,
        )
