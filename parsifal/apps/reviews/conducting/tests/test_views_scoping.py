from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.models import Article, SearchSession
from parsifal.apps.reviews.tests.factories import ReviewFactory, SelectionCriteriaFactory, SourceFactory

BIBTEX = "@article{key1, title={A study}, author={Someone}, year={2020}}"


class TestConductingScopedToTheReview(TestCase):
    """Conducting endpoints only use the review's own sources and criteria."""

    @classmethod
    def setUpTestData(cls):
        cls.member = UserFactory()
        cls.mine = ReviewFactory(author=cls.member)
        cls.my_source = SourceFactory(name="My library")
        cls.mine.sources.add(cls.my_source)
        cls.theirs = ReviewFactory()
        cls.their_source = SourceFactory(name="Their library")
        cls.theirs.sources.add(cls.their_source)
        cls.their_criteria = SelectionCriteriaFactory(review=cls.theirs, description="Theirs", criteria_type="E")

    def setUp(self):
        self.client.force_login(self.member)

    def test_importing_into_another_reviews_source_is_not_found(self):
        url = reverse("reviews:conducting:import_bibtex_raw_content")
        data = {"review-id": self.mine.pk, "source-id": self.their_source.pk, "bibtex_file": BIBTEX}
        self.assertEqual(404, self.client.post(url, data).status_code)
        self.assertFalse(Article.objects.filter(source=self.their_source).exists())
        data["source-id"] = self.my_source.pk
        self.assertEqual(302, self.client.post(url, data).status_code)
        self.assertTrue(Article.objects.filter(review=self.mine, source=self.my_source).exists())

    def test_search_strings_only_for_the_reviews_sources(self):
        url = reverse("reviews:conducting:save_source_string")
        data = {"review-id": self.mine.pk, "source-id": self.their_source.pk, "search_string": "x"}
        self.assertEqual(400, self.client.post(url, data).status_code)
        self.assertFalse(SearchSession.objects.filter(source=self.their_source, review=self.mine).exists())
        url = reverse("reviews:conducting:add_source_string")
        self.client.post(url, {"review-id": self.mine.pk, "source": [self.their_source.pk, self.my_source.pk]})
        self.assertEqual([self.my_source.pk], list(self.mine.searchsession_set.values_list("source", flat=True)))

    def test_new_study_form_needs_one_of_the_reviews_sources(self):
        url = reverse("reviews:conducting:new_article")
        response = self.client.get(url, {"review-id": self.mine.pk, "source-id": self.their_source.pk})
        self.assertEqual(404, response.status_code)
        response = self.client.get(url, {"review-id": self.mine.pk, "source-id": self.my_source.pk})
        self.assertEqual(200, response.status_code)

    def test_a_study_cannot_take_another_reviews_criterion(self):
        article = Article.objects.create(review=self.mine, source=self.my_source, title="Mine", status="R")
        fields = (
            "bibtex-key title author journal year pages volume abstract document-type doi url affiliation "
            "author_keywords keywords publisher issn language note comments"
        ).split()
        data = {name: "" for name in fields}
        data.update(
            {
                "review-id": self.mine.pk,
                "article-id": article.pk,
                "title": "Mine",
                "status": "R",
                "selection_criteria": self.their_criteria.pk,
            }
        )
        response = self.client.post(reverse("reviews:conducting:save_article_details"), data)
        self.assertEqual(200, response.status_code)
        article.refresh_from_db()
        self.assertIsNone(article.selection_criteria)
