from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.conducting.views import build_article_table_row
from parsifal.apps.reviews.models import Article, StudyDecision
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
    SourceFactory,
)


class TestDecisionViews(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.human = UserFactory(username="alice")
        cls.agent = UserFactory(username="agent")
        cls.outsider = UserFactory()
        cls.review = ReviewFactory(author=cls.human, co_authors=[cls.agent], sources=[cls.source])
        cls.criteria = SelectionCriteriaFactory(review=cls.review, description="Relevant")
        cls.a1, cls.a2 = ArticleFactory.create_batch(2, review=cls.review, source=cls.source)

    def test_study_list_has_a_search_box_and_each_row_its_doi(self):
        Article.objects.filter(pk=self.a1.pk).update(doi='10.1/"x"')
        self.client.force_login(self.human)
        response = self.client.get(
            reverse("reviews:conducting:source_articles"), {"review-id": self.review.pk, "source-id": "None"}
        )
        self.assertContains(response, 'placeholder="Search title, DOI or BibTeX key"', html=False)
        self.assertContains(response, f'<tr oid="{self.a1.pk}" article-status="U" article-doi="10.1/&quot;x&quot;">')
        self.a1.refresh_from_db()
        self.assertIn('article-doi="10.1/&quot;x&quot;"', build_article_table_row(self.a1))  # row after a save

    def test_article_details_shows_reviewers_tab(self):
        StudyDecision.objects.create(review=self.review, article=self.a1, user=self.agent, status="A")
        self.client.force_login(self.human)
        response = self.client.get(
            reverse("reviews:conducting:article_details"), {"review-id": self.review.pk, "article-id": self.a1.pk}
        )
        self.assertContains(response, "Reviewers")
        self.assertContains(response, "agent")
        self.assertContains(response, "btn-record-decision")
        # The pane is moved inside <form id="article-details"> by JS; a nested <form> would be dropped by browsers.
        self.assertContains(response, 'id="decision-form"')
        self.assertNotContains(response, '<form id="decision-form"')
        self.assertNotContains(response, "{#")  # multi-line {# #} comments are rendered as text by Django

    def test_record_decision(self):
        self.client.force_login(self.human)
        response = self.client.post(
            reverse("reviews:conducting:record_decision"),
            {
                "review-id": self.review.pk,
                "article-id": self.a1.pk,
                "status": "R",
                "stage": "title_abstract",
                "selection_criteria": self.criteria.pk,
                "comments": "out of scope",
            },
        )
        self.assertEqual(200, response.status_code)
        self.assertContains(response, "Your decision was recorded.")
        decision = StudyDecision.objects.get(article=self.a1, user=self.human)
        self.assertEqual(
            ("R", self.criteria, "out of scope"), (decision.status, decision.selection_criteria, decision.comments)
        )
        with self.subTest(msg="consolidated status untouched"):
            self.a1.refresh_from_db()
            self.assertEqual(Article.UNCLASSIFIED, self.a1.status)
        with self.subTest(msg="invalid status"):
            response = self.client.post(
                reverse("reviews:conducting:record_decision"),
                {"review-id": self.review.pk, "article-id": self.a1.pk, "status": "Z"},
            )
            self.assertEqual(400, response.status_code)
        with self.subTest(msg="outsider forbidden"):
            self.client.force_login(self.outsider)
            response = self.client.post(
                reverse("reviews:conducting:record_decision"),
                {"review-id": self.review.pk, "article-id": self.a1.pk, "status": "A"},
            )
            self.assertEqual(403, response.status_code)

    def test_agreement_and_consolidate(self):
        for article, human, agent in ((self.a1, "A", "A"), (self.a2, "A", "R")):
            StudyDecision.objects.create(review=self.review, article=article, user=self.human, status=human)
            StudyDecision.objects.create(review=self.review, article=article, user=self.agent, status=agent)
        self.client.force_login(self.human)

        response = self.client.get(reverse("reviews:conducting:agreement"), {"review-id": self.review.pk})
        self.assertEqual(200, response.status_code)
        self.assertContains(response, "agent × alice")
        self.assertContains(response, "Cohen")
        self.assertContains(response, self.a2.title)  # the disagreement
        # each disagreement opens its article (on the Reviewers tab, from the page's script)
        self.assertContains(response, f'class="js-open-article" data-article-id="{self.a2.pk}"', html=False)
        self.assertNotContains(response, f'data-article-id="{self.a1.pk}"', html=False)
        self.assertEqual(
            400,
            self.client.get(
                reverse("reviews:conducting:agreement"), {"review-id": self.review.pk, "stage": "x"}
            ).status_code,
        )

        response = self.client.post(
            reverse("reviews:conducting:consolidate"),
            {"review-id": self.review.pk, "stage": "title_abstract", "rule": "unanimous"},
        )
        self.assertEqual(200, response.status_code)
        self.assertContains(response, "1 article(s) updated, 1 left unresolved")
        self.assertContains(response, "rule <strong>Unanimous</strong> at stage <strong>Title and abstract")
        self.assertNotContains(response, "<strong>title_abstract</strong>")
        self.a1.refresh_from_db()
        self.a2.refresh_from_db()
        self.assertEqual(("A", "U"), (self.a1.status, self.a2.status))
        self.assertEqual(
            400,
            self.client.post(
                reverse("reviews:conducting:consolidate"), {"review-id": self.review.pk, "rule": "coin"}
            ).status_code,
        )

    def test_agreement_without_decisions(self):
        self.client.force_login(self.human)
        response = self.client.get(reverse("reviews:conducting:agreement"), {"review-id": self.review.pk})
        self.assertContains(response, "No independent decisions yet")
        self.assertContains(response, "At least two reviewers")
