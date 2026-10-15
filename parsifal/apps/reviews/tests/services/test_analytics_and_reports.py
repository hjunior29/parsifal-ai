from django.test import TestCase

from parsifal.apps.reviews.models import DataExtractionField
from parsifal.apps.reviews.services import analytics, extraction, reports
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    DataExtractionFieldFactory,
    DataExtractionLookupFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
    SourceFactory,
)


class TestAnalytics(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.scopus = SourceFactory(name="Scopus")
        cls.ieee = SourceFactory(name="IEEE")
        cls.review = ReviewFactory(sources=[cls.scopus, cls.ieee])
        ArticleFactory(review=cls.review, source=cls.scopus, status="A", year="2020")
        ArticleFactory(review=cls.review, source=cls.scopus, status="A", year="2021")
        ArticleFactory(review=cls.review, source=cls.scopus, status="R", year="2021")
        ArticleFactory(review=cls.review, source=cls.ieee, status="A", year="n.d.")

    def test_selection_by_source(self):
        rows = analytics.selection_by_source(self.review)
        self.assertEqual([("IEEE", 1, 1), ("Scopus", 3, 2)], [(r["source"], r["total"], r["accepted"]) for r in rows])

    def test_final_selection_by_year(self):
        rows = analytics.final_selection_by_year(self.review)
        self.assertEqual([(2021, 1), (2020, 1), (None, 1)], [(r["year"], r["count"]) for r in rows])


class TestReports(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory(name="Scopus")
        cls.review = ReviewFactory(sources=[cls.source], title="Report SLR")
        cls.criteria = SelectionCriteriaFactory(review=cls.review, description="Relevant")
        cls.accepted = ArticleFactory(
            review=cls.review, source=cls.source, status="A", title="Accepted one", selection_criteria=cls.criteria
        )
        cls.rejected = ArticleFactory(review=cls.review, source=cls.source, status="R", title="Rejected one")
        cls.text_field = DataExtractionFieldFactory(review=cls.review, description="Notes")
        cls.many_field = DataExtractionFieldFactory(
            review=cls.review, description="Methods", field_type=DataExtractionField.SELECT_MANY_FIELD
        )
        cls.lookups = [DataExtractionLookupFactory(field=cls.many_field, value=v) for v in ("Case study", "Survey")]

    def test_articles_rows(self):
        columns, rows = reports.articles_rows(self.review)
        self.assertEqual("bibtex_key", columns[0])
        self.assertEqual(2, len(rows))
        row = next(r for r in rows if r["title"] == "Accepted one")
        self.assertEqual(("Scopus", "Relevant", "Accepted"), (row["source"], row["selection_criteria"], row["status"]))

    def test_extraction_rows_final_selection_only(self):
        extraction.set_value(review=self.review, article_id=self.accepted.pk, field_id=self.text_field.pk, value="ok")
        extraction.set_value(
            review=self.review,
            article_id=self.accepted.pk,
            field_id=self.many_field.pk,
            values=[lk.pk for lk in self.lookups],
        )
        columns, rows = reports.extraction_rows(self.review)
        self.assertEqual(["article", "Notes", "Methods"], columns)
        self.assertEqual([{"article": "Accepted one", "Notes": "ok", "Methods": "Case study, Survey"}], rows)

    def test_build_docx(self):
        document = reports.build_docx(self.review, ["name", "sources", "bogus"])
        texts = [p.text for p in document.paragraphs]
        self.assertIn("Report SLR", texts)
        self.assertTrue(any(t.startswith("Scopus (https://") for t in texts))
        self.assertIn("Planning", texts)
