from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.reviews.models import Article, StudyDecision
from parsifal.apps.reviews.services import decisions
from parsifal.apps.reviews.tests.factories import ArticleFactory


class TestSelectionResetApi(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.accepted = ArticleFactory(review=self.review, source=self.source, status=Article.ACCEPTED)
        self.duplicate = ArticleFactory(review=self.review, source=self.source, status=Article.DUPLICATED)
        for actor in (self.author, self.co_author):
            decisions.record_decision(review=self.review, article_id=self.accepted.pk, actor=actor, status="A")
        self.path = self.review_path("/selection/reset")

    def test_reset(self):
        response = self.api("post", self.path, {"reviewer_ids": [self.co_author.pk]})
        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual({"unclassified": 1, "decisions_deleted": 1, "runs_discarded": 0}, response.json())
        self.accepted.refresh_from_db()
        self.duplicate.refresh_from_db()
        self.assertEqual((Article.UNCLASSIFIED, Article.DUPLICATED), (self.accepted.status, self.duplicate.status))
        self.assertEqual([self.author.pk], list(StudyDecision.objects.values_list("user_id", flat=True)))
        self.assertEqual(
            {"unclassified": 0, "decisions_deleted": 0, "runs_discarded": 0}, self.api("post", self.path, {}).json()
        )

    def test_main_author_only_and_known_reviewers(self):
        refused = self.api("post", self.path, {}, client=self.client_for(self.co_author))
        self.assertEqual(403, refused.status_code)
        self.assertEqual(404, self.api("post", self.path, {}, client=self.client_for(self.outsider)).status_code)
        unknown = self.api("post", self.path, {"reviewer_ids": [self.outsider.pk]})
        self.assertEqual((404, "reviewer_ids"), (unknown.status_code, unknown.json()["field"]))
        self.accepted.refresh_from_db()
        self.assertEqual(Article.ACCEPTED, self.accepted.status)
        self.assertEqual(2, StudyDecision.objects.count())
