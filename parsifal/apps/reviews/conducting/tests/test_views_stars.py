from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.conducting.views import build_article_table_row
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory, SourceFactory


class TestStarViews(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.author = UserFactory(username="alice")
        cls.outsider = UserFactory()
        cls.review = ReviewFactory(author=cls.author, sources=[cls.source])
        cls.a1, cls.a2 = ArticleFactory.create_batch(2, review=cls.review, source=cls.source)

    def setUp(self):
        self.client.force_login(self.author)

    def star(self, article, starred="1"):
        return self.client.post(
            reverse("reviews:conducting:star_article"),
            {"review-id": self.review.pk, "article-id": article.pk, "starred": starred},
        )

    def study_list(self):
        return self.client.get(
            reverse("reviews:conducting:source_articles"), {"review-id": self.review.pk, "source-id": "None"}
        )

    def test_toggle_returns_the_star(self):
        response = self.star(self.a1)
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'class="js-star starred"')
        self.assertContains(response, f'data-article-id="{self.a1.pk}"')
        self.assertContains(response, "Starred by alice on")
        self.assertContains(response, "glyphicon-star")
        self.assertNotContains(response, "glyphicon-star-empty")
        self.assertTrue(Article.objects.get(pk=self.a1.pk).starred)

        response = self.star(self.a1, "0")
        self.assertContains(response, 'class="js-star"')
        self.assertContains(response, "Star this study in the review")
        self.assertContains(response, "glyphicon-star-empty")
        self.assertFalse(Article.objects.get(pk=self.a1.pk).starred)

        self.client.force_login(self.outsider)
        self.assertEqual(403, self.star(self.a1).status_code)

    def test_the_list_has_a_star_column_apart_from_the_status_and_a_filter_by_the_search(self):
        self.star(self.a1)
        response = self.study_list()
        content = response.content.decode()
        self.assertContains(response, 'class="star-header"')
        self.assertContains(response, f'<tr oid="{self.a1.pk}" article-status="U"', html=False)
        self.assertContains(response, 'article-starred="1"')
        self.assertContains(response, 'article-starred="0"')
        # The filter sits with the search, not with the statuses of "Show", and counts the starred studies.
        self.assertContains(response, 'js-starred-filter" aria-pressed="false"')
        self.assertContains(response, '<span class="starred-count">1</span>', html=True)
        self.assertLess(content.index("js-starred-filter"), content.index("js-article-search"))
        self.assertGreater(content.index('name="filter" value="ALL"'), content.index("js-article-search"))
        # The status has its own cell, so updating it never touches the star.
        self.assertContains(
            response, '<td class="js-status"><span class="label label-default">Unclassified</span></td>'
        )
        self.assertNotContains(response, 'value="star"')  # no bulk star in the Action menu

        row = build_article_table_row(Article.objects.get(pk=self.a1.pk))
        self.assertIn('article-starred="1"', row)
        self.assertIn('class="js-star starred"', row)

    def test_the_study_window_carries_its_star_for_the_title(self):
        self.star(self.a2)
        response = self.client.get(
            reverse("reviews:conducting:article_details"), {"review-id": self.review.pk, "article-id": self.a2.pk}
        )
        self.assertContains(response, 'id="article-star-source"')
        self.assertContains(response, 'class="js-star starred"')
        response = self.client.get(
            reverse("reviews:conducting:new_article"), {"review-id": self.review.pk, "source-id": self.source.pk}
        )
        self.assertNotContains(response, "article-star-source")
