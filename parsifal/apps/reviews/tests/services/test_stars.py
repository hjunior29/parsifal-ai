from django.test import TestCase

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.exceptions import NotFound
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.services import studies
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory, SourceFactory


class TestStars(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.author = UserFactory(username="alice")
        cls.agent = UserFactory(username="agent")
        cls.review = ReviewFactory(author=cls.author, co_authors=[cls.agent], sources=[cls.source])
        cls.article, cls.other = ArticleFactory.create_batch(
            2, review=cls.review, source=cls.source, status=Article.REJECTED
        )
        Article.objects.filter(pk=cls.article.pk).update(updated_by=cls.agent)

    def star(self, starred=True, actor=None, article=None):
        return studies.set_starred(
            review=self.review, article_id=(article or self.article).pk, starred=starred, actor=actor or self.author
        )

    def test_one_shared_star_per_study(self):
        before = Article.objects.get(pk=self.article.pk)
        article = self.star()
        self.assertTrue(article.starred)
        self.assertEqual(self.author, article.starred_by)
        first = article.starred_at
        with self.subTest(msg="starring again keeps who starred it first"):
            article = self.star(actor=self.agent)
            self.assertEqual((self.author, first), (article.starred_by, article.starred_at))
        with self.subTest(msg="any status, and the status and who set it are untouched"):
            self.assertEqual(
                (Article.REJECTED, self.agent.pk, before.updated_at),
                (article.status, article.updated_by_id, article.updated_at),
            )
        with self.subTest(msg="anyone unstars it"):
            article = self.star(starred=False, actor=self.agent)
            self.assertEqual((False, None, None), (article.starred, article.starred_by, article.starred_at))
            self.assertFalse(self.star(starred=False).starred)  # unstarring twice is harmless

    def test_list_filter(self):
        self.star()
        self.assertEqual([self.article], list(studies.list_articles(self.review, starred=True)))
        self.assertEqual([self.other], list(studies.list_articles(self.review, starred=False)))
        self.assertEqual(2, studies.list_articles(self.review).count())
        self.assertEqual([self.article], list(studies.list_articles(self.review, starred=True, status="R")))

    def test_scoped_to_the_review(self):
        with self.assertRaises(NotFound):
            self.star(article=ArticleFactory())
