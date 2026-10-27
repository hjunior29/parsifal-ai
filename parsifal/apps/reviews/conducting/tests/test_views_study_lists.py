import re

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.tests.files import PDF, TemporaryFilesMixin
from parsifal.apps.reviews.models import DataExtractionField
from parsifal.apps.reviews.services import full_texts, quality
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    DataExtractionFieldFactory,
    QualityAnswerFactory,
    QualityQuestionFactory,
    ReviewFactory,
    SourceFactory,
)


class StudyListsTestCase(TestCase):
    """Quality Assessment and Data Extraction list their studies a page at a time, each closed until opened."""

    @classmethod
    def setUpTestData(cls):
        cls.author = UserFactory()
        cls.source = SourceFactory()
        cls.review = ReviewFactory(author=cls.author, sources=[cls.source])
        cls.questions = QualityQuestionFactory.create_batch(2, review=cls.review)
        cls.yes = QualityAnswerFactory(review=cls.review, description="Yes", weight=1.0)
        cls.field = DataExtractionFieldFactory(review=cls.review, description="Notes")
        DataExtractionFieldFactory(review=cls.review, field_type=DataExtractionField.BOOLEAN_FIELD)
        cls.articles = [
            ArticleFactory(review=cls.review, source=cls.source, status="A", title=f"Study {index:02d}", year="2020")
            for index in range(1, 31)
        ]
        quality.assess(
            review=cls.review, article_id=cls.articles[0].pk, question_id=cls.questions[0].pk, answer_id=cls.yes.pk
        )

    def setUp(self):
        self.client.force_login(self.author)

    @staticmethod
    def panel_titles(response):
        return re.findall(r"</span>\s*(Study \d\d) <small>", response.content.decode())


class TestQualityAssessmentList(StudyListsTestCase):
    def detailed(self, **params):
        return self.client.get(
            reverse("reviews:conducting:quality_assessment_detailed"), {"review-id": self.review.pk, **params}
        )

    def test_the_page_shows_25_closed_panels_with_their_progress(self):
        response = self.client.get(reverse("quality_assessment", args=(self.author.username, self.review.name)))
        self.assertEqual([f"Study {index:02d}" for index in range(1, 26)], self.panel_titles(response))
        self.assertContains(response, '<div class="collapse">', count=25, html=False)
        self.assertContains(response, "1 of 2 answered")
        self.assertContains(response, "0 of 2 answered", count=24)
        self.assertContains(response, 'class="js-open-study"', count=25, html=False)
        self.assertContains(response, "<strong>1</strong>–<strong>25</strong> of <strong>30</strong>", html=False)
        self.assertContains(response, 'id="modal-study"', html=False)

    def test_search_show_order_and_pages(self):
        self.assertEqual([], self.panel_titles(self.detailed(show="done")))  # one of two answered
        quality.assess(
            review=self.review, article_id=self.articles[0].pk, question_id=self.questions[1].pk, answer_id=self.yes.pk
        )
        self.assertEqual(["Study 01"], self.panel_titles(self.detailed(show="done")))
        self.assertEqual(["Study 01"], self.panel_titles(self.detailed(show="above")))  # no cutoff: above 0
        self.assertEqual(["Study 10"], self.panel_titles(self.detailed(q="study 10", part="list")))
        self.assertEqual(["Study 30", "Study 29"], self.panel_titles(self.detailed(order="-title"))[:2])
        self.assertEqual("-title", self.client.session["quality_assessment_order"])  # kept for the next time
        response = self.detailed(page="2", order="title", part="list")
        self.assertEqual([f"Study {index}" for index in range(26, 31)], self.panel_titles(response))
        self.assertNotContains(response, "js-study-search")  # part=list: the studies and the pager only
        response = self.detailed(q="nothing like it", part="list")
        self.assertContains(response, "No studies match the search")

    def test_the_answer_marked_and_the_checklist_rows(self):
        response = self.detailed(q="study 01", part="list")
        self.assertContains(response, f'<td class="answer selected-answer" answer-id="{self.yes.pk}">', html=False)
        self.assertContains(response, f'question-id="{self.questions[1].pk}"', html=False)


class TestDataExtractionList(StudyListsTestCase):
    def page(self, **params):
        return self.client.get(reverse("data_extraction", args=(self.author.username, self.review.name)), params)

    def test_the_tab_shows_25_closed_panels_with_their_fields_filled(self):
        response = self.page(tab="all")
        self.assertEqual([f"Study {index:02d}" for index in range(1, 26)], self.panel_titles(response))
        self.assertContains(response, '<div class="collapse">', count=25, html=False)
        self.assertContains(response, "0 of 2 fields", count=25)
        self.assertContains(response, 'name="q"', html=False)
        self.assertContains(response, 'id="modal-study"', html=False)

    def test_search_done_and_pages(self):
        self.client.post(
            reverse("reviews:conducting:save_data_extraction"),
            {"review-id": self.review.pk, "article-id": self.articles[2].pk, "field-id": self.field.pk, "value": "x"},
        )
        response = self.page(tab="all", q="study 03", part="list")
        self.assertEqual(["Study 03"], self.panel_titles(response))
        self.assertContains(response, "1 of 2 fields")
        self.assertNotContains(response, "data-extraction-menu")  # part=list: the studies and the pager only
        self.assertEqual(
            [f"Study {index}" for index in range(26, 31)], self.panel_titles(self.page(tab="todo", page="2"))
        )
        self.assertContains(self.page(tab="done"), "No studies marked as done yet.")
        self.assertContains(self.page(tab="all", q="nothing like it"), "No studies match the search.")


class TestStudyWindow(TemporaryFilesMixin, StudyListsTestCase):
    def window(self, article):
        return self.client.get(
            reverse("reviews:conducting:study_window"), {"review-id": self.review.pk, "article-id": article.pk}
        )

    def test_the_study_to_read_without_screening_it(self):
        article = self.articles[0]
        response = self.window(article)
        self.assertContains(response, f'data-article-id="{article.pk}"', html=False)
        self.assertContains(response, article.title)
        self.assertContains(response, "Abstract")
        self.assertNotContains(response, 'name="status"')  # nothing here screens it
        self.assertNotContains(response, "selection_criteria")
        self.assertContains(response, '<li role="presentation" class="active">', html=False)
        self.assertContains(response, "Upload PDF")  # the full text may come now

    def test_it_opens_on_the_full_text_when_there_is_one(self):
        article = self.articles[1]
        full_texts.attach_pdf(
            review=self.review,
            article_id=article.pk,
            file=SimpleUploadedFile("study.pdf", PDF, content_type="application/pdf"),
            actor=self.author,
        )
        response = self.window(article)
        content = response.content.decode()
        self.assertIn('class="tab-pane active" id="study-full-text"', content)
        self.assertIn(reverse("reviews:conducting:article_pdf", args=(article.pk,)), content)

    def test_scoping(self):
        foreign = ArticleFactory()
        self.assertEqual(404, self.window(foreign).status_code)
        self.client.force_login(UserFactory())
        self.assertEqual(403, self.window(self.articles[0]).status_code)
