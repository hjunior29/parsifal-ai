from django.contrib.auth.models import User
from django.test import TestCase

from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.exceptions import NotFound, PermissionDenied, ValidationError
from parsifal.apps.reviews.models import Article, DataExtraction, QualityAssessment, ReviewAgent, StudyDecision
from parsifal.apps.reviews.services import agents
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    DataExtractionFieldFactory,
    QualityAnswerFactory,
    QualityQuestionFactory,
    ReviewFactory,
    SourceFactory,
)


class TestAgents(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserFactory()
        cls.source = SourceFactory()
        cls.review = ReviewFactory(author=cls.owner, sources=[cls.source])

    def create(self, name="Screening bot"):
        return agents.create_agent(review=self.review, actor=self.owner, name=name)

    def test_create_makes_a_co_author_account_with_a_token(self):
        created = self.create()
        user = created.agent.user
        self.assertEqual(("agent-screening-bot", "Screening bot"), (user.username, created.agent.name))
        self.assertFalse(user.has_usable_password())
        self.assertTrue(self.review.is_author_or_coauthor(user))
        self.assertEqual(user, ApiToken.objects.authenticate(created.raw_key))
        self.assertEqual([created.agent], agents.list_agents(self.review))

    def test_usernames_are_unique_and_valid(self):
        first, second = self.create("Bot"), self.create("Bot")
        self.assertEqual(("agent-bot", "agent-bot-2"), (first.agent.user.username, second.agent.user.username))
        self.assertEqual("agent-bot-3", self.create("bot").agent.user.username)
        self.assertEqual("agent", self.create("???").agent.user.username)

    def test_name_is_required_and_limited(self):
        for name in ("", "   ", "x" * 51):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                self.create(name)

    def test_only_the_main_author_manages_agents(self):
        created = self.create()
        agent_user = created.agent.user
        for call in (
            lambda: agents.create_agent(review=self.review, actor=agent_user, name="Child"),
            lambda: agents.new_token(review=self.review, actor=agent_user, agent_id=agent_user.pk),
            lambda: agents.delete_agent(review=self.review, actor=agent_user, agent_id=agent_user.pk),
        ):
            with self.assertRaises(PermissionDenied):
                call()
        self.assertTrue(User.objects.filter(pk=agent_user.pk).exists())

    def test_new_token_revokes_the_old_ones(self):
        created = self.create()
        renewed = agents.new_token(review=self.review, actor=self.owner, agent_id=created.agent.user_id)
        self.assertIsNone(ApiToken.objects.authenticate(created.raw_key))
        self.assertEqual(created.agent.user, ApiToken.objects.authenticate(renewed.raw_key))
        self.assertEqual(1, created.agent.user.api_tokens.active().count())

    def test_agent_of_another_review_is_not_found(self):
        other = ReviewFactory()
        foreign = agents.create_agent(review=other, actor=other.author, name="Theirs")
        with self.assertRaises(NotFound):
            agents.delete_agent(review=self.review, actor=self.owner, agent_id=foreign.agent.user_id)
        self.assertTrue(User.objects.filter(pk=foreign.agent.user_id).exists())

    def test_delete_removes_account_token_and_everything_recorded(self):
        created = self.create()
        user = created.agent.user
        article = ArticleFactory(review=self.review, source=self.source, created_by=user)
        kept_decision_author = StudyDecision.objects.create(
            review=self.review, article=article, user=self.owner, status=Article.ACCEPTED
        )
        StudyDecision.objects.create(review=self.review, article=article, user=user, status=Article.REJECTED)
        question, answer = QualityQuestionFactory(review=self.review), QualityAnswerFactory(review=self.review)
        QualityAssessment.objects.create(user=user, article=article, question=question, answer=answer)
        field = DataExtractionFieldFactory(review=self.review)
        DataExtraction.objects.create(user=user, article=article, field=field, value="x")

        self.assertEqual(
            {"decisions": 1, "quality_assessments": 1, "data_extractions": 1, "active_tokens": 1},
            agents.stats(created.agent),
        )
        deleted = agents.delete_agent(review=self.review, actor=self.owner, agent_id=user.pk)

        self.assertEqual(1, deleted["decisions"])
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(ReviewAgent.objects.exists())
        self.assertIsNone(ApiToken.objects.authenticate(created.raw_key))
        self.assertEqual([kept_decision_author], list(StudyDecision.objects.all()))
        self.assertFalse(QualityAssessment.objects.exists())
        self.assertFalse(DataExtraction.objects.exists())
        article.refresh_from_db()
        self.assertIsNone(article.created_by)

    def test_deleting_the_review_deletes_its_agents(self):
        created = self.create()
        self.review.delete()
        self.assertFalse(User.objects.filter(pk=created.agent.user_id).exists())
        self.assertTrue(User.objects.filter(pk=self.owner.pk).exists())
