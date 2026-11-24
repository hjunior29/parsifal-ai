import datetime

from django.test import TestCase

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import Review, ReviewEvent
from parsifal.apps.reviews.services import mapping, progress, rapid, reports, reviews, threats
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory
from parsifal.apps.reviews.tests.services.test_report_sections import texts


class TestRapidReview(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory(review_type=Review.RAPID, title="RR")

    def test_the_type(self):
        self.assertTrue(self.review.is_rapid_review)
        other = ReviewFactory()
        reviews.update_review(review=other, review_type="rapid")
        self.assertTrue(other.is_rapid_review)
        with self.assertRaises(ValidationError) as raised:
            reviews.update_review(review=other, review_type="quick")
        self.assertIn("'slr', 'mapping', 'rapid'", str(raised.exception))

    def test_practical_context(self):
        reviews.update_review(
            review=self.review,
            demand="practitioners",
            practical_problem="Too many defects escape to production.",
            started_on="2026-11-02",
            deadline="2026-11-09",
        )
        self.review.refresh_from_db()
        self.assertEqual(
            ("practitioners", datetime.date(2026, 11, 2), datetime.date(2026, 11, 9)),
            (self.review.demand, self.review.started_on, self.review.deadline),
        )
        event = self.review.events.order_by("pk").last()
        self.assertEqual(ReviewEvent.PLANNING, event.area)
        self.assertIn("Practical problem", event.summary)
        for fields in ({"demand": "boss"}, {"started_on": "02/11/2026"}, {"deadline": "2026-11-01"}):
            with self.subTest(fields=fields):
                with self.assertRaises(ValidationError):
                    reviews.update_review(review=self.review, **fields)
        reviews.update_review(review=self.review, started_on="", demand="")
        self.review.refresh_from_db()
        self.assertEqual((None, ""), (self.review.started_on, self.review.demand))

    def test_the_checklist_is_for_rapid_reviews_only(self):
        result = mapping.checklist(self.review, mapping.RAPID)
        self.assertEqual((0, len(rapid.RAPID_CHECKLIST)), (result["applied"], result["total"]))
        single = next(item for item in result["items"] if item["key"] == "rr_single_source")
        self.assertEqual(("Search", "A single search source"), (single["phase"], single["label"]))
        self.assertIn("Only one search source", single["threat"])
        slr = ReviewFactory()
        with self.assertRaises(ValidationError):
            mapping.checklist(slr, mapping.RAPID)
        with self.assertRaises(ValidationError):
            mapping.set_checklist_item(review=slr, key="rr_single_source", applied=True)
        with self.assertRaises(ValidationError):
            mapping.checklist(self.review, "other")
        self.assertEqual("petersen", mapping.checklist(slr)["catalog"])

    def test_a_concession_is_part_of_the_protocol(self):
        ArticleFactory(review=self.review)
        mapping.set_checklist_item(
            review=self.review, key="rr_single_source", applied=True, notes="Scopus indexes the main venues."
        )
        event = self.review.events.order_by("pk").last()
        self.assertEqual(
            ("Changed the rapid review checklist item “A single search source”", ReviewEvent.PLANNING, True),
            (event.summary, event.area, event.amendment),
        )
        self.assertIn(
            {"key": "notes", "field": "Justification", "before": "", "after": "Scopus indexes the main venues."},
            event.changes,
        )

    def test_draft_the_threats_from_the_concessions(self):
        for key, notes in (
            ("rr_single_source", "Scopus indexes the main venues."),
            ("rr_one_reviewer", ""),
            ("rr_problem_with_practitioners", "A focus group"),  # not a concession: no threat
        ):
            mapping.set_checklist_item(review=self.review, key=key, applied=True, notes=notes)
        threats.add_threat(review=self.review, title="Studies selected by one reviewer", mitigation="Mine")
        added = rapid.draft_threats(review=self.review)
        self.assertEqual(
            [("A single search source", "Theoretical validity", "Scopus indexes the main venues.")],
            [(threat.title, threat.category, threat.mitigation) for threat in added],
        )
        self.assertIn("Only one search source", added[0].description)
        self.assertEqual("Mine", self.review.threats.get(title="Studies selected by one reviewer").mitigation)
        self.assertEqual([], rapid.draft_threats(review=self.review))  # nothing twice
        event = self.review.events.get(summary__startswith="Drafted")
        self.assertEqual(
            ("Drafted 1 threat to validity from the concessions of the rapid review", ["A single search source"]),
            (event.summary, event.items),
        )
        with self.assertRaises(ValidationError):
            rapid.draft_threats(review=ReviewFactory())

    def test_progress_and_report(self):
        self.assertEqual("practical_problem", progress.progress(self.review)["phases"][0]["steps"][0]["key"])
        self.assertNotIn(
            "quality", {step["key"] for phase in progress.progress(self.review)["phases"] for step in phase["steps"]}
        )
        reviews.update_review(
            review=self.review, demand="agenda", practical_problem="Flaky tests.", started_on="2026-11-02"
        )
        mapping.set_checklist_item(review=self.review, key="rr_one_reviewer", applied=True, notes="Time")
        content = texts(reports.build_docx(self.review))
        for expected in (
            "Practical Context",
            "Demand: The researcher aligned their agenda with practitioners' needs",
            "Practical problem: Flaky tests.",
            "Time frame: 2026-11-02",
            "Rapid Review Checklist (Cartaxo et al. 2020)",
            "[Selection] Studies selected by one reviewer (concession) — Time",
            "Rapid review",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, content)
        slr = ReviewFactory(practical_problem="Not shown")
        self.assertNotIn("Practical Context", texts(reports.build_docx(slr)))
