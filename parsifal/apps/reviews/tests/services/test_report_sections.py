from django.test import TestCase

from parsifal.apps.reviews.models import Review
from parsifal.apps.reviews.services import classification, extraction, mapping, quality, reports, reviews, search
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    DataExtractionFieldFactory,
    QualityAnswerFactory,
    QualityQuestionFactory,
    ReviewFactory,
    SourceFactory,
)


def texts(document):
    chunks = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            chunks.extend(cell.text for cell in row.cells)
    return "\n".join(chunks)


class TestExtendedReportSections(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory(name="Scopus")
        cls.review = ReviewFactory(sources=[cls.source], review_type=Review.MAPPING, title="Map SLR")
        reviews.update_review(
            review=cls.review,
            selection_procedure="Two reviewers screen independently.",
            synthesis_strategy="Frequencies and bubble plots.",
            validity_threats="Descriptive validity: data form.",
        )
        search.set_source_search_string(review=cls.review, source_id=cls.source.pk, search_string="a AND b")
        search.update_source_search(
            review=cls.review,
            source_id=cls.source.pk,
            search_type="database",
            searched_at="2026-10-01",
            years_from=2015,
            years_to=2026,
            result_count=120,
        )
        cls.article = ArticleFactory(
            review=cls.review, source=cls.source, status="A", title="Known paper", year="2020"
        )
        question = QualityQuestionFactory(review=cls.review)
        yes = QualityAnswerFactory(review=cls.review, description="Yes", weight=1.0)
        quality.assess(review=cls.review, article_id=cls.article.pk, question_id=question.pk, answer_id=yes.pk)
        field = DataExtractionFieldFactory(review=cls.review, description="Tool")
        extraction.set_value(review=cls.review, article_id=cls.article.pk, field_id=field.pk, value="ReviewBot")
        facet = classification.add_facet_from_template(review=cls.review, template="research_type")
        category = facet.categories.get(name="Evaluation research")
        classification.classify(
            review=cls.review, article_id=cls.article.pk, facet_id=facet.pk, category_ids=[category.pk]
        )
        mapping.add_test_set_article(review=cls.review, title="Known Paper")
        mapping.set_checklist_item(review=cls.review, key="search_database", applied=True, notes="Scopus")

    def test_all_sections_render(self):
        document = reports.build_docx(self.review)  # all sections
        content = texts(document)
        expectations = (
            "Systematic mapping study",
            "Two reviewers screen independently.",
            "Frequencies and bubble plots.",
            "Descriptive validity: data form.",
            "Classification Scheme",
            "Research type (Fixed (topic-independent)): Evaluation research",
            "1 of 1 known papers were retrieved by the search (100%).",
            "Search Documentation",
            "2015–2026",
            "120",
            "Maximum score: 1.0. Cutoff: 0.0.",
            "Known paper",
            "ReviewBot",
            "Classification Results",
            "Evaluation research (1)",
            "Scopus 1 / 1",
            "2020: 1",
            "1 of 26 recommended actions applied (4%).",
            "[Study identification] Conduct database search — Scopus",
        )
        for expected in expectations:
            with self.subTest(expected=expected):
                self.assertIn(expected, content)

    def test_sections_are_optional(self):
        document = reports.build_docx(self.review, ["name"])
        content = texts(document)
        self.assertIn("Map SLR", content)
        self.assertNotIn("Search Documentation", content)
        self.assertNotIn("ReviewBot", content)
