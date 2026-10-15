from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.tests.factories import ReviewFactory, SourceFactory


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
