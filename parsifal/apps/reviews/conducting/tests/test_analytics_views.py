from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.models import Article, DataExtractionField
from parsifal.apps.reviews.services import extraction, quality
from parsifal.apps.reviews.tests.factories import (
    DataExtractionFieldFactory,
    DataExtractionLookupFactory,
    QualityAnswerFactory,
    QualityQuestionFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
    SourceFactory,
)


class AnalyticsViewsTestMixin:
    url_name = None

    @classmethod
    def setUpTestData(cls):
        cls.author = UserFactory()
        cls.co_author = UserFactory()
        cls.outsider = UserFactory()
        cls.source = SourceFactory()
        cls.review = ReviewFactory(author=cls.author, co_authors=[cls.co_author], sources=[cls.source])
        Article.objects.create(review=cls.review, source=cls.source, title="Accepted", year="2020", status="A")
        Article.objects.create(review=cls.review, source=cls.source, title="Rejected", year="2021", status="R")
        cls.url = reverse(cls.url_name)

    def get(self):
        return self.client.get(self.url, {"review-id": self.review.pk})

    def test_anonymous_forbidden(self):
        response = self.get()
        self.assertEqual(403, response.status_code)

    def test_outsider_forbidden(self):
        self.client.force_login(self.outsider)
        response = self.get()
        self.assertEqual(403, response.status_code)

    def test_co_author_allowed(self):
        self.client.force_login(self.co_author)
        response = self.get()
        self.assertEqual(200, response.status_code)


class TestArticlesSelectionChart(AnalyticsViewsTestMixin, TestCase):
    url_name = "reviews:conducting:articles_selection_chart"

    def test_counts_per_source(self):
        self.client.force_login(self.author)
        response = self.get()
        self.assertEqual(f"{self.source.name}:2:1", response.content.decode())


class TestArticlesPerYear(AnalyticsViewsTestMixin, TestCase):
    url_name = "reviews:conducting:articles_per_year"

    def test_counts_final_selection_per_year(self):
        self.client.force_login(self.author)
        response = self.get()
        self.assertEqual("2020:1", response.content.decode())


class TestDataAnalysisSections(TestCase):
    """Data Analysis has three sections: the study selection, the quality assessment and the data extraction."""

    @classmethod
    def setUpTestData(cls):
        cls.author = UserFactory()
        cls.source = SourceFactory()
        cls.review = ReviewFactory(author=cls.author, sources=[cls.source])
        cls.article = Article.objects.create(review=cls.review, source=cls.source, title="Accepted", status="A")
        cls.url = reverse("data_analysis", args=(cls.author.username, cls.review.name))

    def setUp(self):
        self.client.force_login(self.author)

    def test_the_study_selection_first(self):
        response = self.client.get(self.url)
        self.assertEqual("selection", response.context["section"])
        self.assertContains(
            response, '<li class="active"><a href="?section=selection">Study Selection</a></li>', html=True
        )
        self.assertContains(response, 'id="analysis-funnel"', html=False)
        self.assertNotContains(response, 'id="analysis-quality"', html=False)
        self.assertEqual("selection", self.client.get(self.url, {"section": "nope"}).context["section"])

    def test_the_prisma_diagram_and_its_not_retrieved_criterion(self):
        missing = self.review.selectioncriteria_set.create(criteria_type="E", description="Full text missing")
        self.review.selectioncriteria_set.create(criteria_type="I", description="Proposes a tool")
        response = self.client.get(self.url)
        self.assertContains(response, "PRISMA 2020 Flow Diagram")
        self.assertContains(response, 'id="analysis-prisma-data"', html=False)
        self.assertContains(response, f'<option value="{missing.pk}">Full text missing</option>', html=True)
        self.assertNotContains(response, "Proposes a tool</option>", html=False)  # exclusion criteria only
        self.assertEqual(1, response.context["prisma"]["awaiting_full_text"])  # accepted, no full-text decision
        url = reverse("reviews:conducting:save_prisma_settings")
        data = {"review-id": self.review.pk, "not-retrieved-criteria-id": missing.pk}
        self.assertEqual(405, self.client.get(url, data).status_code)
        response = self.client.post(url, data)
        self.assertEqual(missing.pk, response.json()["not_retrieved_criteria_id"])
        self.review.refresh_from_db()
        self.assertEqual(missing, self.review.prisma_not_retrieved)
        self.assertContains(
            self.client.get(self.url), f'<option value="{missing.pk}" selected>Full text missing</option>', html=True
        )
        self.assertIsNone(self.client.post(url, {"review-id": self.review.pk}).json()["not_retrieved_criteria_id"])
        other = SelectionCriteriaFactory(criteria_type="E")
        refused = self.client.post(url, {"review-id": self.review.pk, "not-retrieved-criteria-id": other.pk})
        self.assertEqual(400, refused.status_code)

    def test_quality_assessment(self):
        response = self.client.get(self.url, {"section": "quality"})
        self.assertContains(response, "has no quality checklist yet")
        question = QualityQuestionFactory(review=self.review)
        answer = QualityAnswerFactory(review=self.review, weight=1.0)
        quality.assess(review=self.review, article_id=self.article.pk, question_id=question.pk, answer_id=answer.pk)
        response = self.client.get(self.url, {"section": "quality"})
        self.assertContains(response, "Quality Assessment in Numbers")
        self.assertContains(response, 'id="analysis-scores"', html=False)
        self.assertContains(response, 'id="analysis-questions"', html=False)
        self.assertEqual(
            [("studies", 1), ("assessed", 1), ("partly", 0), ("not_assessed", 0)],
            [(stage["key"], stage["count"]) for stage in response.context["stages"]],
        )
        self.assertNotContains(response, 'id="analysis-funnel"', html=False)

    def test_data_extraction_draws_the_choice_fields_only(self):
        response = self.client.get(self.url, {"section": "extraction"})
        self.assertContains(response, "has no data extraction form yet")
        text = DataExtractionFieldFactory(review=self.review, description="Notes")
        response = self.client.get(self.url, {"section": "extraction"})
        self.assertContains(response, "no single choice, multiple choice or true/false field to draw")
        many = DataExtractionFieldFactory(
            review=self.review, description="Artifacts", field_type=DataExtractionField.SELECT_MANY_FIELD
        )
        lookup = DataExtractionLookupFactory(field=many, value="Code")
        extraction.set_value(review=self.review, article_id=self.article.pk, field_id=many.pk, values=[lookup.pk])
        response = self.client.get(self.url, {"section": "extraction"})
        self.assertContains(response, f'id="analysis-field-{many.pk}"', html=False)
        self.assertNotContains(response, f'id="analysis-field-{text.pk}"', html=False)
        self.assertContains(response, "multiple choice: a study may have several")
        self.assertContains(response, "1 of 1 study of the final selection answered.")
        self.assertEqual(
            [("selected", 1), ("done", 0), ("todo", 1)],
            [(stage["key"], stage["count"]) for stage in response.context["stages"]],
        )
