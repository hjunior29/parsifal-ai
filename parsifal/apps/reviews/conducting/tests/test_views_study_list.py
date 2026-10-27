import re

from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.services import studies
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory, SourceFactory


class TestStudyListPages(TestCase):
    """The study list of Study Selection comes a page at a time, filtered and sorted on the server."""

    @classmethod
    def setUpTestData(cls):
        cls.author = UserFactory()
        cls.source, cls.other_source = SourceFactory(), SourceFactory()
        cls.review = ReviewFactory(author=cls.author, sources=[cls.source, cls.other_source])
        cls.articles = [
            ArticleFactory(
                review=cls.review,
                source=cls.source,
                title=f"Study {index:02d}",
                status=Article.ACCEPTED if index % 3 == 0 else Article.UNCLASSIFIED,
            )
            for index in range(1, 31)
        ]
        ArticleFactory(review=cls.review, source=cls.other_source, title="Elsewhere")
        cls.url = reverse("reviews:conducting:source_articles")

    def setUp(self):
        self.client.force_login(self.author)

    def get(self, **params):
        return self.client.get(self.url, {"review-id": self.review.pk, "source-id": self.source.pk, **params})

    def titles(self, response):
        return re.findall(r'article-title="([^"]*)"', response.content.decode())

    def test_the_first_page_has_25_studies_and_a_pager(self):
        response = self.get()
        self.assertEqual([f"Study {index:02d}" for index in range(1, 26)], self.titles(response))
        self.assertContains(
            response, "<strong>1</strong>–<strong>25</strong> of <strong>30</strong> studies", html=False
        )
        self.assertContains(response, 'data-page="2"', html=False)
        self.assertContains(response, '<option value="25" selected>25</option>', html=True)
        self.assertContains(response, 'data-count="30"', html=False)
        self.assertContains(response, "js-article-search")  # the tab's controls come with its first page

    def test_another_page_and_size(self):
        self.assertEqual(["Study 26", "Study 27", "Study 28", "Study 29", "Study 30"], self.titles(self.get(page=2)))
        response = self.get(**{"per-page": "10", "page": "3"})
        self.assertEqual([f"Study {index}" for index in range(21, 31)], self.titles(response))
        with self.subTest(msg="the size is kept for the next time"):
            self.assertEqual(10, len(self.titles(self.get())))
            self.assertEqual(10, self.client.session["studies_per_page"])
        with self.subTest(msg="past the last page: the last; a size not offered: 25"):
            self.assertEqual(["Study 30"], self.titles(self.get(**{"per-page": "29", "page": "99"}))[-1:])
            self.assertEqual(25, self.client.session["studies_per_page"])
            self.assertEqual(25, len(self.titles(self.get(page="nope"))))

    def test_filters_search_and_star_cover_every_page(self):
        accepted = self.titles(self.get(status="A"))
        self.assertEqual([f"Study {index:02d}" for index in range(3, 31, 3)], accepted)
        self.assertEqual([f"Study {index}" for index in range(20, 30)], self.titles(self.get(q="study 2")))
        studies.set_starred(review=self.review, article_id=self.articles[28].pk, starred=True)
        self.assertEqual(["Study 29"], self.titles(self.get(starred="1")))
        response = self.get(q="nothing like it")
        self.assertContains(response, "No articles match the search and filters.")
        self.assertNotContains(response, "conducting-pager")

    def test_the_headings_sort_the_list(self):
        response = self.get(order="-title", part="list")
        self.assertEqual("Study 30", self.titles(response)[0])
        self.assertContains(response, 'class="header headerSortUp" data-order="title"', html=False)
        self.assertContains(response, 'class="header ai-header" data-order="ai_score"', html=False)
        self.assertNotContains(response, "js-article-search")  # part=list: the table and its pager only
        self.assertEqual(400, self.get(order="nope").status_code)

    def test_every_source_and_scoping(self):
        response = self.client.get(self.url, {"review-id": self.review.pk, "source-id": "None", "q": "Elsewhere"})
        self.assertEqual(["Elsewhere"], self.titles(response))
        foreign = SourceFactory()
        self.assertEqual(404, self.get(**{"source-id": foreign.pk}).status_code)
        self.client.force_login(UserFactory())
        self.assertEqual(403, self.get().status_code)
