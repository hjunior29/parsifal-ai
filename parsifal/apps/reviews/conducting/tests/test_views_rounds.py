"""The round mode of Study Selection (rapid reviews): the list of a round, and a status that is also a decision."""

from django.test import TestCase
from django.urls import reverse

from parsifal.apps.reviews.models import Article, Review, StudyDecision
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
    SourceFactory,
)

FIELDS = ("bibtex-key", "author", "journal", "year", "pages", "volume", "abstract", "document-type", "doi", "url")
FIELDS += ("affiliation", "author_keywords", "keywords", "publisher", "issn", "language", "note", "comments")


def conducting(name):
    return reverse(f"reviews:conducting:{name}")


class RoundModeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(review_type=Review.RAPID, sources=[cls.source])
        cls.criterion = SelectionCriteriaFactory(review=cls.review, criteria_type="E", description="Off topic")

    def setUp(self):
        self.client.force_login(self.review.author)
        self.one = ArticleFactory(review=self.review, source=self.source, title="One", abstract="Secret abstract")
        self.two = ArticleFactory(review=self.review, source=self.source, title="Two")

    def test_the_list_of_a_round(self):
        page = self.client.get(conducting("source_articles"), {"review-id": self.review.pk, "source-id": "None"})
        self.assertContains(page, "js-round")
        self.assertContains(page, "Title screening")
        StudyDecision.objects.create(
            review=self.review, article=self.one, user=self.review.author, stage="title", status="A"
        )
        listed = self.client.get(
            conducting("source_articles"),
            {
                "review-id": self.review.pk,
                "source-id": "None",
                "round": "title",
                "round-state": "pending",
                "part": "list",
            },
        )
        self.assertContains(listed, "Two")
        self.assertNotContains(listed, ">One<", html=False)

    def test_bulk_and_details_record_the_decision(self):
        response = self.client.post(
            conducting("multiple_articles_action_reject"),
            {"review-id": self.review.pk, "article_ids": str(self.two.pk), "round": "title"},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            [("Two", "title", "R")], list(self.review.decisions.values_list("article__title", "stage", "status"))
        )
        data = {"review-id": self.review.pk, "article-id": self.one.pk, "source-id": self.source.pk}
        data.update({name: "" for name in FIELDS}, title="One", abstract="Secret abstract", status="A")
        data.update(selection_criteria="", round="title")
        self.assertEqual(200, self.client.post(conducting("save_article_details"), data).status_code)
        self.assertEqual("A", self.review.decisions.get(article=self.one).status)
        self.assertEqual(
            "Accepted the study “One” (Title screening)", self.review.events.order_by("pk").last().summary
        )

    def test_the_title_round_hides_the_abstract(self):
        details = self.client.get(
            conducting("article_details"), {"review-id": self.review.pk, "article-id": self.one.pk, "round": "title"}
        )
        self.assertContains(details, "Show the abstract")
        self.assertContains(details, 'name="round" value="title"', html=False)
        plain = self.client.get(
            conducting("article_details"), {"review-id": self.review.pk, "article-id": self.one.pk}
        )
        self.assertNotContains(plain, "Show the abstract")

    def test_other_reviews_have_no_round(self):
        other = ReviewFactory(author=self.review.author, sources=[self.source])
        study = ArticleFactory(review=other, source=self.source)
        page = self.client.get(conducting("source_articles"), {"review-id": other.pk, "source-id": "None"})
        self.assertNotContains(page, "js-round")
        self.client.post(
            conducting("multiple_articles_action_accept"),
            {"review-id": other.pk, "article_ids": str(study.pk), "round": "title"},  # ignored
        )
        study.refresh_from_db()
        self.assertEqual((Article.ACCEPTED, 0), (study.status, other.decisions.count()))
