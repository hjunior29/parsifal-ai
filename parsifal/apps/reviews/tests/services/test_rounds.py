"""The screening rounds of a rapid review: title → title and abstract → full text (Cartaxo et al. 2020 §4.2.2)."""

from django.test import TestCase

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import Article, Review, StudyDecision
from parsifal.apps.reviews.services import ai_screening, analytics, decisions, reviews, screening_requests, studies
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory, SelectionCriteriaFactory
from parsifal.apps.reviews.tests.services.test_ai_screening import EXCLUDE_E2, KEEP, AiScreeningTestCase

TITLE, TITLE_ABSTRACT, FULL_TEXT = StudyDecision.TITLE, StudyDecision.TITLE_ABSTRACT, StudyDecision.FULL_TEXT
A, R, U, D = Article.ACCEPTED, Article.REJECTED, Article.UNCLASSIFIED, Article.DUPLICATED


class RoundsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory(review_type=Review.RAPID)
        cls.me = cls.review.author
        cls.colleague = UserFactory()
        cls.review.co_authors.add(cls.colleague)
        cls.criterion = SelectionCriteriaFactory(review=cls.review, criteria_type="E", description="Off topic")

    def study(self, title, status=U):
        return ArticleFactory(review=self.review, title=title, status=status)

    def decide(self, article, stage, status, user=None):
        return decisions.record_decision(
            review=self.review, article_id=article.pk, actor=user or self.me, status=status, stage=stage
        )

    def titles(self, stage, state=None, user=None):
        queryset = studies.list_articles(self.review, stage=stage, stage_state=state, user=user or self.me)
        return sorted(article.title for article in queryset)


class TestStages(RoundsTestCase):
    def test_the_stages_of_each_type(self):
        self.assertEqual([TITLE, TITLE_ABSTRACT, FULL_TEXT], self.review.stages())
        self.assertEqual(TITLE, self.review.first_stage)
        slr = ReviewFactory()
        self.assertEqual([TITLE_ABSTRACT, FULL_TEXT], slr.stages())
        study = ArticleFactory(review=slr)
        with self.assertRaises(ValidationError):
            decisions.record_decision(review=slr, article_id=study.pk, actor=slr.author, status=R, stage=TITLE)
        decision = decisions.record_decision(review=slr, article_id=study.pk, actor=slr.author, status=R)
        self.assertEqual(TITLE_ABSTRACT, decision.stage)

    def test_a_rapid_reviews_first_stage_is_the_title(self):
        self.assertEqual(TITLE, self.decide(self.study("One"), None, R).stage)
        self.assertEqual([TITLE], [row["stage"] for row in decisions.summary(self.review)])

    def test_the_type_stays_rapid_while_the_title_round_has_decisions(self):
        self.decide(self.study("One"), TITLE, R)
        with self.assertRaises(ValidationError):
            reviews.update_review(review=self.review, review_type="slr")
        self.review.decisions.all().delete()
        reviews.update_review(review=self.review, review_type="slr")
        self.assertFalse(self.review.is_rapid_review)


class TestQueue(RoundsTestCase):
    def test_who_is_in_each_round(self):
        out = self.study("Out at the title")
        passed = self.study("Passed the title", status=A)
        later = self.study("Decided at the abstract", status=R)
        self.study("Duplicate", status=D)
        self.study("Not screened yet")
        self.study("Accepted before the rounds", status=A)
        self.decide(out, TITLE, R)
        self.decide(passed, TITLE, A)
        self.decide(later, TITLE, A)
        self.decide(later, TITLE_ABSTRACT, R)
        self.assertEqual(
            [
                "Accepted before the rounds",
                "Decided at the abstract",
                "Not screened yet",
                "Out at the title",
                "Passed the title",
            ],
            self.titles(TITLE),
        )
        self.assertEqual(["Accepted before the rounds", "Not screened yet"], self.titles(TITLE, "pending"))
        self.assertEqual(["Decided at the abstract", "Passed the title"], self.titles(TITLE_ABSTRACT))
        self.assertEqual(["Passed the title"], self.titles(TITLE_ABSTRACT, "pending"))
        # Pending for each reviewer: the colleague has decided nothing at the round.
        self.assertEqual(
            ["Decided at the abstract", "Passed the title"], self.titles(TITLE_ABSTRACT, "pending", self.colleague)
        )
        self.assertEqual(["Decided at the abstract"], self.titles(TITLE_ABSTRACT, "decided"))
        self.assertEqual([], self.titles(FULL_TEXT))
        with self.assertRaises(ValidationError):
            self.titles(TITLE, "later")
        with self.assertRaises(ValidationError):
            studies.list_articles(ReviewFactory(), stage=TITLE_ABSTRACT, user=self.me)


class TestRoundMode(RoundsTestCase):
    def test_a_status_given_at_a_round_is_also_my_decision_there(self):
        one, two = self.study("One"), self.study("Two")
        studies.set_status(
            review=self.review,
            article_ids=[one.pk, two.pk],
            status=R,
            selection_criteria_id=self.criterion.pk,
            actor=self.me,
            stage=TITLE,
        )
        rows = list(
            self.review.decisions.values_list("article__title", "user", "stage", "status", "selection_criteria")
        )
        self.assertEqual(
            {("One", self.me.pk, TITLE, R, self.criterion.pk), ("Two", self.me.pk, TITLE, R, self.criterion.pk)},
            set(rows),
        )
        events = list(self.review.events.order_by("pk"))
        self.assertEqual(["Rejected 2 studies (Off topic) (Title screening)"], [event.summary for event in events])
        studies.set_status(review=self.review, article_ids=[one.pk], status=U, actor=self.me, stage=TITLE)
        self.assertEqual(["Two"], list(self.review.decisions.values_list("article__title", flat=True)))
        studies.set_status(review=self.review, article_ids=[two.pk], status=D, actor=self.me, stage=TITLE)
        self.assertEqual(R, self.review.decisions.get().status)  # a duplicate is no decision: the one there stays
        with self.assertRaises(ValidationError):
            other = ReviewFactory()
            studies.set_status(
                review=other, article_ids=[ArticleFactory(review=other).pk], status=A, actor=self.me, stage=TITLE
            )


class TestAnalysis(RoundsTestCase):
    def test_prisma_and_the_funnel(self):
        out = self.study("Out at the title", status=R)
        self.decide(out, TITLE, R)
        later = self.study("Out at the abstract", status=R)
        self.decide(later, TITLE, A)
        self.decide(later, TITLE_ABSTRACT, R)
        kept = self.study("Included", status=A)
        for stage in (TITLE, TITLE_ABSTRACT, FULL_TEXT):
            self.decide(kept, stage, A)
        self.study("Waiting")
        self.study("Duplicate", status=D)
        result = analytics.prisma(self.review)
        self.assertEqual((2, 1), (result["excluded"], result["included"]))
        self.assertEqual(
            [("title", "Title screening", 1), ("title_abstract", "Title and abstract screening", 1)],
            [(row["stage"], row["label"], row["excluded"]) for row in result["excluded_by_round"]],
        )
        self.assertEqual(
            [
                ("records", 4, None),
                ("title", 2, 1),
                ("title_abstract", 1, 0),
                ("full_text", 1, 0),
            ],
            [(row["key"], row["studies"], row["pending"]) for row in analytics.selection_funnel(self.review)],
        )
        self.assertIsNone(analytics.prisma(ReviewFactory())["excluded_by_round"])
        with self.assertRaises(ValidationError):
            analytics.selection_funnel(ReviewFactory())


class TestTitleRequest(TestCase):
    def test_the_title_round_sends_the_title_only(self):
        template = screening_requests.default("exclusion", TITLE)
        self.assertEqual({"title": "{{study.title}}"}, template["state"]["study"])
        task = template["question"]["instructions"]["task"]
        self.assertEqual(
            "Screening for a systematic review, from the title of a study: which exclusion criterion does it clearly "
            "indicate that the study meets?",
            task,
        )
        self.assertNotIn("abstract", str(screening_requests.default("inclusion", TITLE)))
        self.assertIn("abstract", str(screening_requests.default("inclusion")))
        screening_requests.clean("exclusion", template)  # a valid request


class TestAiRounds(AiScreeningTestCase):
    def test_a_run_screens_at_a_round(self):
        Review.objects.filter(pk=self.review.pk).update(review_type=Review.RAPID)
        self.review.refresh_from_db()
        first, second = self.article(title="First"), self.article(title="Second")
        run = self.start(stage=TITLE)
        self.assertEqual((TITLE, False), (run.parameters["stage"], run.parameters["pending"]))
        self.assertEqual({"title": "{{study.title}}"}, run.parameters["template"]["state"]["study"])
        self.step(run, [EXCLUDE_E2, KEEP])
        self.assertEqual(
            {(first.pk, TITLE, R), (second.pk, TITLE, U)},
            set(StudyDecision.objects.filter(user=self.bot).values_list("article", "stage", "status")),
        )
        self.assertIn("(Title screening)", self.review.events.filter(summary__startswith="Started").get().summary)
        # Only the studies of the round the reviewer has not decided yet: none left.
        with self.assertRaises(ValidationError):
            self.start(stage=TITLE, pending=True, statuses=["U", "R"])
        self.assertEqual(TITLE, ai_screening.starting_settings(self.review, "exclusion")["stage"])

    def test_other_reviews_have_no_rounds(self):
        self.article()
        with self.assertRaises(ValidationError):
            self.start(stage=TITLE)
        with self.assertRaises(ValidationError):
            self.start(pending=True)
        self.assertEqual(TITLE_ABSTRACT, self.start().parameters["stage"])
