from django.test import TestCase

from parsifal.apps.reviews.models import DataExtractionField
from parsifal.apps.reviews.services import analytics, extraction, quality, reports
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    DataExtractionFieldFactory,
    DataExtractionLookupFactory,
    QualityAnswerFactory,
    QualityQuestionFactory,
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


class TestSelectionAnalytics(TestCase):
    """The numbers and rankings added below the first charts of Data Analysis."""

    @classmethod
    def setUpTestData(cls):
        cls.scopus = SourceFactory(name="Scopus")
        cls.ieee = SourceFactory(name="IEEE")
        cls.review = ReviewFactory(sources=[cls.scopus, cls.ieee])
        # Listed alphabetically: "Not a primary study" (E1), "Not in English" (E2); "About tools" (I1).
        cls.primary = SelectionCriteriaFactory(review=cls.review, criteria_type="E", description="Not a primary study")
        cls.english = SelectionCriteriaFactory(review=cls.review, criteria_type="E", description="Not in English")
        cls.tools = SelectionCriteriaFactory(review=cls.review, criteria_type="I", description="About tools")
        for status, criterion, year, source in (
            ("R", cls.english, "2021", cls.scopus),
            ("R", cls.english, "2022", cls.scopus),
            ("R", cls.primary, "2022", cls.ieee),
            ("R", None, "2022", cls.ieee),
            ("A", cls.tools, "2022", cls.scopus),
            ("A", None, "n.d.", cls.scopus),
            ("U", None, "2021", cls.ieee),
            ("D", None, "2021", cls.scopus),
            ("D", None, "2021", cls.scopus),
            ("U", None, "2023", cls.scopus),
        ):
            ArticleFactory(review=cls.review, source=source, status=status, selection_criteria=criterion, year=year)

    def test_selection_summary(self):
        summary = analytics.selection_summary(self.review)
        self.assertEqual(
            (10, 2, 8, 2, 4, 2, 2),
            tuple(
                summary[k] for k in ("total", "duplicated", "unique", "accepted", "rejected", "unclassified", "final")
            ),
        )
        self.assertEqual(
            (0.2, 0.25, 0.5, 0.25),
            tuple(summary[f"{k}_share"] for k in ("duplicated", "accepted", "rejected", "unclassified")),
        )
        self.assertEqual(
            [("IEEE", 3, 0, 2, 1, 0), ("Scopus", 7, 2, 2, 1, 2)],
            [
                (r["source"], r["total"], r["accepted"], r["rejected"], r["unclassified"], r["duplicated"])
                for r in summary["by_source"]
            ],
        )
        empty = analytics.selection_summary(ReviewFactory())
        self.assertEqual((0, None, None), (empty["total"], empty["duplicated_share"], empty["accepted_share"]))

    def test_criteria_most_used_first(self):
        usage = analytics.criteria_usage(self.review)
        self.assertEqual(
            [("E2", "Not in English", 2), ("E1", "Not a primary study", 1)],
            [(r["key"], r["description"], r["studies"]) for r in usage["exclusion"]],
        )
        self.assertEqual([("I1", 1)], [(r["key"], r["studies"]) for r in usage["inclusion"]])
        self.assertEqual((1, 1), (usage["rejected_without_criterion"], usage["accepted_without_criterion"]))

    def test_studies_by_year_without_duplicates(self):
        self.assertEqual(
            [
                {"year": 2021, "accepted": 0, "rejected": 1, "unclassified": 1},
                {"year": 2022, "accepted": 1, "rejected": 3, "unclassified": 0},
                {"year": 2023, "accepted": 0, "rejected": 0, "unclassified": 1},
                {"year": None, "accepted": 1, "rejected": 0, "unclassified": 0},
            ],
            analytics.studies_by_year(self.review),
        )


class TestQualityAndExtractionAnalytics(TestCase):
    """The Quality Assessment and Data Extraction sections of Data Analysis."""

    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source], quality_assessment_cutoff_score=1.0)
        cls.q1, cls.q2 = QualityQuestionFactory.create_batch(2, review=cls.review)
        cls.yes = QualityAnswerFactory(review=cls.review, description="Yes", weight=1.0)
        cls.no = QualityAnswerFactory(review=cls.review, description="No", weight=0.0)
        cls.good, cls.weak, cls.fresh = (
            ArticleFactory(review=cls.review, source=cls.source, status="A", title=title)
            for title in ("Good", "Weak", "Fresh")
        )
        rejected = ArticleFactory(review=cls.review, source=cls.source, status="R")
        for article, answers in ((cls.good, (cls.yes, cls.yes)), (cls.weak, (cls.no,)), (rejected, (cls.yes,))):
            for question, answer in zip((cls.q1, cls.q2), answers):
                quality.assess(review=cls.review, article_id=article.pk, question_id=question.pk, answer_id=answer.pk)

    def test_quality_overview(self):
        overview = analytics.quality_overview(self.review)
        self.assertEqual(
            (3, 2, 1, 1, 1, 1.0, 1, 2, 2.0),
            (
                overview["accepted"],
                overview["questions"],
                overview["assessed"],
                overview["partly"],
                overview["not_assessed"],
                overview["cutoff"],
                overview["above_cutoff"],
                overview["at_most_cutoff"],
                overview["max_score"],
            ),
        )
        self.assertEqual([{"score": 2.0, "studies": 1}], overview["scores"])  # only the fully assessed
        self.assertEqual(["Yes", "No"], [answer["description"] for answer in overview["answers"]])
        q1, q2 = overview["by_question"]
        self.assertEqual(("Q1", [1, 1], 1), (q1["key"], [a["studies"] for a in q1["answers"]], q1["unanswered"]))
        self.assertEqual(("Q2", [1, 0], 2), (q2["key"], [a["studies"] for a in q2["answers"]], q2["unanswered"]))
        with self.subTest(msg="no cutoff"):
            quality.set_cutoff(review=self.review, cutoff=0)
            self.assertEqual(
                (None, None, None),
                tuple(
                    analytics.quality_overview(self.review)[key]
                    for key in ("cutoff", "above_cutoff", "at_most_cutoff")
                ),
            )

    def test_extraction_choices(self):
        one = DataExtractionFieldFactory(review=self.review, field_type=DataExtractionField.SELECT_ONE_FIELD)
        many = DataExtractionFieldFactory(review=self.review, field_type=DataExtractionField.SELECT_MANY_FIELD)
        flag = DataExtractionFieldFactory(review=self.review, field_type=DataExtractionField.BOOLEAN_FIELD)
        DataExtractionFieldFactory(review=self.review)  # text: left out
        survey, case = DataExtractionLookupFactory(field=one, value="Survey"), DataExtractionLookupFactory(
            field=one, value="Case study"
        )
        code, tests = DataExtractionLookupFactory(field=many, value="Code"), DataExtractionLookupFactory(
            field=many, value="Tests"
        )
        # The final selection: Good (score 2.0 > 1.0); Weak and Fresh are at most the cutoff.
        for article in (self.good, self.weak):
            extraction.set_value(review=self.review, article_id=article.pk, field_id=one.pk, value=survey.pk)
            extraction.set_value(
                review=self.review, article_id=article.pk, field_id=many.pk, values=[code.pk, tests.pk]
            )
            extraction.set_value(review=self.review, article_id=article.pk, field_id=flag.pk, value="False")
        extraction.mark_done(review=self.review, article_id=self.good.pk)
        choices = analytics.extraction_choices(self.review)
        self.assertEqual((1, 1), (choices["studies"], choices["done"]))
        by_id = {field["id"]: field for field in choices["fields"]}
        self.assertEqual([one.pk, many.pk, flag.pk], [field["id"] for field in choices["fields"]])
        self.assertEqual(
            [("Survey", 1), ("Case study", 0)], [(o["value"], o["studies"]) for o in by_id[one.pk]["options"]]
        )
        self.assertEqual([("Code", 1), ("Tests", 1)], [(o["value"], o["studies"]) for o in by_id[many.pk]["options"]])
        self.assertEqual([("True", 0), ("False", 1)], [(o["value"], o["studies"]) for o in by_id[flag.pk]["options"]])
        self.assertEqual((1, 0), (by_id[many.pk]["answered"], by_id[many.pk]["unanswered"]))
        self.assertEqual(case.pk, by_id[one.pk]["options"][1]["id"])


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
