from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.tests.factories import ArticleFactory


class TestStarsApi(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.article, cls.other = ArticleFactory.create_batch(
            2, review=cls.review, source=cls.source, status=Article.ACCEPTED
        )

    def star_path(self, article=None):
        return self.review_path(f"/articles/{(article or self.article).pk}/star")

    def test_star_list_and_unstar(self):
        body = self.api("get", self.review_path(f"/articles/{self.article.pk}")).json()
        self.assertEqual((False, None, None), (body["starred"], body["starred_by"], body["starred_at"]))

        body = self.api("put", self.star_path(), client=self.client_for(self.co_author)).json()
        self.assertEqual((True, self.co_author.username, "A"), (body["starred"], body["starred_by"], body["status"]))
        self.assertIsNotNone(body["starred_at"])

        starred = self.api("get", self.review_path("/articles?starred=true")).json()
        self.assertEqual([self.article.pk], [a["id"] for a in starred["items"]])
        others = self.api("get", self.review_path("/articles?starred=false")).json()
        self.assertEqual([self.other.pk], [a["id"] for a in others["items"]])

        body = self.api("delete", self.star_path()).json()  # the author unstars the co-author's star
        self.assertEqual((False, None), (body["starred"], body["starred_by"]))

    def test_members_only(self):
        outsider = self.client_for(self.outsider)
        self.assertEqual(404, self.api("put", self.star_path(), client=outsider).status_code)
        self.assertEqual(404, self.api("delete", self.star_path(), client=outsider).status_code)
        self.assertEqual(404, self.api("put", self.star_path(ArticleFactory())).status_code)
