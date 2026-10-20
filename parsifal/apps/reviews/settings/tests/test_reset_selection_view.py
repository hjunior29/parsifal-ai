from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.models import Article, ScreeningRun, StudyDecision
from parsifal.apps.reviews.services import agents, decisions
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory, SourceFactory
from parsifal.utils.test import login_redirect_url


class TestResetSelectionView(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.co_author = UserFactory()
        cls.review = ReviewFactory(sources=[cls.source], co_authors=[cls.co_author])
        cls.owner = cls.review.author
        cls.bot = agents.create_agent(review=cls.review, actor=cls.owner, name="Screener").agent.user
        cls.settings_url = reverse("settings", args=(cls.owner.username, cls.review.name))
        cls.url = reverse("reset_selection", args=(cls.owner.username, cls.review.name))

    def setUp(self):
        self.rejected = ArticleFactory(review=self.review, source=self.source, status=Article.REJECTED)
        self.duplicate = ArticleFactory(review=self.review, source=self.source, status=Article.DUPLICATED)
        for actor in (self.bot, self.owner):
            decisions.record_decision(review=self.review, article_id=self.rejected.pk, actor=actor, status="R")
        ScreeningRun.objects.create(review=self.review, reviewer=self.bot, status=ScreeningRun.FINISHED, total=1)

    def test_danger_zone_asks_for_confirmation(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.settings_url)
        self.assertContains(response, "Reset the study selection")
        self.assertContains(response, 'id="confirm-reset" class="btn btn-danger btn-block" disabled', html=False)
        self.assertContains(response, 'id="enable-confirm-reset"')
        self.assertContains(response, "<strong>1</strong> study goes back to unclassified", html=False)
        self.assertContains(response, "Duplicates stay duplicates (1).")
        self.assertContains(response, "the log of the 1 AI screening run ")
        # AI agents are checked by default, people are not.
        self.assertContains(response, f'name="reviewer_ids" value="{self.bot.pk}" checked>', html=False)
        self.assertContains(response, f'name="reviewer_ids" value="{self.owner.pk}">', html=False)

    def test_reset_and_go_to_study_selection(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {"reviewer_ids": [self.bot.pk]}, follow=True)
        self.assertRedirects(response, reverse("study_selection", args=(self.owner.username, self.review.name)))
        self.assertContains(
            response, "The study selection was reset: 1 study is unclassified again, 1 decision deleted."
        )
        self.rejected.refresh_from_db()
        self.duplicate.refresh_from_db()
        self.assertEqual((Article.UNCLASSIFIED, Article.DUPLICATED), (self.rejected.status, self.duplicate.status))
        self.assertEqual([self.owner.pk], list(StudyDecision.objects.values_list("user_id", flat=True)))
        self.assertEqual(1, ScreeningRun.objects.count())

    def test_errors_go_back_to_the_settings(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.url, {"reviewer_ids": ["bot"]}, follow=True)
        self.assertRedirects(response, self.settings_url)
        self.assertContains(response, "reviewer_ids must be user ids.")
        self.rejected.refresh_from_db()
        self.assertEqual(Article.REJECTED, self.rejected.status)

    def test_main_author_only(self):
        self.assertRedirects(self.client.post(self.url), login_redirect_url(self.url))
        self.client.force_login(self.co_author)
        self.assertEqual(403, self.client.post(self.url).status_code)
        self.client.force_login(self.owner)
        self.assertEqual(405, self.client.get(self.url).status_code)
        self.rejected.refresh_from_db()
        self.assertEqual(Article.REJECTED, self.rejected.status)
