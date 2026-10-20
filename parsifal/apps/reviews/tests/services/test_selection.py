from django.test import TestCase
from django.utils import timezone

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.exceptions import NotFound, PermissionDenied, ValidationError
from parsifal.apps.reviews.models import Article, ScreeningResult, ScreeningRun, SelectionCriteria, StudyDecision
from parsifal.apps.reviews.services import agents, decisions, selection
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory, SourceFactory


class SelectionResetTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.co_author = UserFactory(username="b-co-author")
        cls.review = ReviewFactory(sources=[cls.source], co_authors=[cls.co_author])
        cls.owner = cls.review.author
        cls.bot = agents.create_agent(review=cls.review, actor=cls.owner, name="Screener").agent.user
        cls.criterion = SelectionCriteria.objects.create(review=cls.review, criteria_type="E", description="Out")

    def setUp(self):
        self.someone = UserFactory()
        self.accepted = self.article(status=Article.ACCEPTED, updated_by=self.someone)
        self.rejected = self.article(status=Article.REJECTED, selection_criteria=self.criterion, updated_by=self.bot)
        self.left_over = self.article(status=Article.UNCLASSIFIED, selection_criteria=self.criterion)
        self.untouched = self.article(status=Article.UNCLASSIFIED, updated_by=self.someone)
        self.duplicate = self.article(status=Article.DUPLICATED, selection_criteria=self.criterion)
        self.accepted.starred_at, self.accepted.starred_by = timezone.now(), self.owner
        self.accepted.save(update_fields=["starred_at", "starred_by"])
        for article in (self.accepted, self.rejected):
            decisions.record_decision(review=self.review, article_id=article.pk, actor=self.bot, status="R")
        decisions.record_decision(review=self.review, article_id=self.accepted.pk, actor=self.owner, status="A")
        decisions.record_decision(
            review=self.review,
            article_id=self.accepted.pk,
            actor=self.bot,
            status="A",
            stage=StudyDecision.FULL_TEXT,
        )
        self.finished = ScreeningRun.objects.create(
            review=self.review, reviewer=self.bot, status=ScreeningRun.FINISHED, total=1
        )
        self.running = ScreeningRun.objects.create(review=self.review, reviewer=self.bot, total=2)
        ScreeningResult.objects.create(run=self.running, article=self.rejected, outcome=ScreeningResult.EXCLUDED)
        ScreeningResult.objects.create(run=self.running, article=self.untouched, previous_status="U")

    def article(self, **kwargs):
        return ArticleFactory(review=self.review, source=self.source, **kwargs)


class TestResetSummary(SelectionResetTestCase):
    def test_what_would_change_and_what_is_kept(self):
        summary = selection.reset_summary(self.review)
        self.assertEqual(
            (1, 1, 2, 1, 3, 2, True),
            tuple(
                summary[key]
                for key in (
                    "accepted",
                    "rejected",
                    "unclassified",
                    "duplicated",
                    "to_unclassify",
                    "runs",
                    "running_run",
                )
            ),
        )
        self.assertEqual(
            {self.bot: (3, True), self.owner: (1, False)},
            {row["user"]: (row["decisions"], row["is_agent"]) for row in summary["reviewers"]},
        )


class TestReset(SelectionResetTestCase):
    def test_back_to_the_start_of_study_selection(self):
        done = selection.reset(review=self.review, actor=self.owner, reviewer_ids=[self.bot.pk])
        self.assertEqual({"unclassified": 3, "decisions_deleted": 3, "runs_discarded": 1}, done)

        for article in (self.accepted, self.rejected, self.left_over):
            with self.subTest(article=article.pk):
                article.refresh_from_db()
                self.assertEqual(
                    (Article.UNCLASSIFIED, None, self.owner),
                    (article.status, article.selection_criteria, article.updated_by),
                )
        with self.subTest(msg="kept: duplicates, studies already unclassified, stars"):
            self.duplicate.refresh_from_db()
            self.untouched.refresh_from_db()
            self.accepted.refresh_from_db()
            self.assertEqual(
                (Article.DUPLICATED, self.criterion), (self.duplicate.status, self.duplicate.selection_criteria)
            )
            self.assertEqual(self.someone, self.untouched.updated_by)
            self.assertTrue(self.accepted.starred)
        with self.subTest(msg="only the chosen reviewers' decisions, at every stage"):
            self.assertFalse(StudyDecision.objects.filter(user=self.bot).exists())
            self.assertEqual(
                ["A"], list(StudyDecision.objects.filter(user=self.owner).values_list("status", flat=True))
            )
        with self.subTest(msg="the run in progress is discarded; the log of the runs is kept"):
            self.running.refresh_from_db()
            self.finished.refresh_from_db()
            self.assertEqual((ScreeningRun.CANCELLED, selection.DISCARDED), (self.running.status, self.running.error))
            self.assertEqual([ScreeningResult.EXCLUDED], list(self.running.results.values_list("outcome", flat=True)))
            self.assertEqual(ScreeningRun.FINISHED, self.finished.status)

        again = selection.reset(review=self.review, actor=self.owner, reviewer_ids=[self.owner.pk])
        self.assertEqual({"unclassified": 0, "decisions_deleted": 1, "runs_discarded": 0}, again)

    def test_reviewers_are_optional_and_checked(self):
        self.assertEqual(0, selection.reset(review=self.review, actor=self.owner)["decisions_deleted"])
        self.assertEqual(4, StudyDecision.objects.count())
        self.assertEqual(
            3,
            selection.reset(review=self.review, actor=self.owner, reviewer_ids=str(self.bot.pk))["decisions_deleted"],
        )
        self.assertEqual(
            0,
            selection.reset(review=self.review, actor=self.owner, reviewer_ids=[self.co_author.pk])[
                "decisions_deleted"
            ],
        )
        with self.assertRaises(NotFound):
            selection.reset(review=self.review, actor=self.owner, reviewer_ids=[self.someone.pk])
        with self.assertRaisesMessage(ValidationError, "user ids"):
            selection.reset(review=self.review, actor=self.owner, reviewer_ids=["bot"])

    def test_only_the_main_author(self):
        for actor in (self.co_author, self.bot):
            with self.subTest(actor=actor.username), self.assertRaisesMessage(PermissionDenied, "main author"):
                selection.reset(review=self.review, actor=actor, reviewer_ids=[self.bot.pk])
        self.rejected.refresh_from_db()
        self.assertEqual(Article.REJECTED, self.rejected.status)
        self.assertEqual(4, StudyDecision.objects.count())
