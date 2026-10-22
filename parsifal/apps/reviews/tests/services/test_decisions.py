from django.test import TestCase

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.exceptions import NotFound, ValidationError
from parsifal.apps.reviews.models import Article, StudyDecision
from parsifal.apps.reviews.services import decisions, reviews
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
    SourceFactory,
)


class TestKappa(TestCase):
    def test_known_values(self):
        with self.subTest(msg="no pairs"):
            self.assertIsNone(decisions.cohens_kappa([]))
        with self.subTest(msg="perfect agreement across categories"):
            self.assertEqual(1.0, decisions.cohens_kappa([("A", "A"), ("R", "R")]))
        with self.subTest(msg="perfect agreement, one category"):
            self.assertEqual(1.0, decisions.cohens_kappa([("A", "A"), ("A", "A")]))
        with self.subTest(msg="chance level"):
            pairs = [("A", "A"), ("A", "R"), ("R", "A"), ("R", "R")]
            self.assertAlmostEqual(0.0, decisions.cohens_kappa(pairs))
        with self.subTest(msg="textbook example: po=0.7, pe=0.5 -> 0.4"):
            pairs = [("A", "A")] * 4 + [("R", "R")] * 3 + [("A", "R")] * 2 + [("R", "A")]
            self.assertAlmostEqual(0.4, decisions.cohens_kappa(pairs))
        with self.subTest(msg="interpretation labels"):
            self.assertEqual("substantial", decisions.interpret_kappa(0.7))
            self.assertEqual("no overlap", decisions.interpret_kappa(None))
            self.assertEqual("poor", decisions.interpret_kappa(-0.2))


class TestDecisions(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.human = UserFactory(username="alice")
        cls.agent = UserFactory(username="claude-agent")
        cls.review = ReviewFactory(author=cls.human, co_authors=[cls.agent], sources=[cls.source])
        cls.criteria = SelectionCriteriaFactory(review=cls.review)
        cls.articles = ArticleFactory.create_batch(4, review=cls.review, source=cls.source)

    def decide(self, user, article, status, **kwargs):
        return decisions.record_decision(
            review=self.review, article_id=article.pk, actor=user, status=status, **kwargs
        )

    def test_record_is_upsert_and_scoped(self):
        a = self.articles[0]
        first = self.decide(self.agent, a, "A", criteria_id=self.criteria.pk, comments="matches RQ1")
        second = self.decide(self.agent, a, "R")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(("R", None, ""), (second.status, second.selection_criteria, second.comments))
        with self.subTest(msg="article status untouched by individual decisions"):
            a.refresh_from_db()
            self.assertEqual(Article.UNCLASSIFIED, a.status)
        with self.assertRaises(ValidationError):
            self.decide(self.agent, a, "X")
        with self.assertRaises(ValidationError):
            self.decide(self.agent, a, "A", stage="screening")
        with self.assertRaises(NotFound):
            decisions.record_decision(review=self.review, article_id=ArticleFactory().pk, actor=self.agent, status="A")
        with self.assertRaises(NotFound):
            self.decide(self.agent, a, "A", criteria_id=SelectionCriteriaFactory().pk)

    def test_bulk_remove_and_listing(self):
        decisions.record_decisions(
            review=self.review, article_ids=[a.pk for a in self.articles], actor=self.agent, status="A"
        )
        self.assertEqual(4, decisions.list_decisions(self.review, user_id=self.agent.pk).count())
        decisions.remove_decision(review=self.review, article_id=self.articles[0].pk, actor=self.agent)
        self.assertEqual(3, decisions.list_decisions(self.review, status="A").count())
        with self.assertRaises(NotFound):
            decisions.remove_decision(review=self.review, article_id=self.articles[0].pk, actor=self.agent)
        self.assertEqual(["claude-agent"], [u.username for u in decisions.reviewers(self.review)])

    def test_agreement_and_disagreements(self):
        a1, a2, a3, a4 = self.articles
        for article, human, agent in ((a1, "A", "A"), (a2, "R", "R"), (a3, "A", "R"), (a4, "R", "R")):
            self.decide(self.human, article, human)
            self.decide(self.agent, article, agent)
        report = decisions.agreement(review=self.review)
        self.assertEqual(
            ("alice", "claude-agent", 4, 3, 0.75),
            (report["user_a"], report["user_b"], report["compared"], report["agreed"], report["percent_agreement"]),
        )
        self.assertAlmostEqual(0.5, report["kappa"])
        self.assertEqual("moderate", report["interpretation"])

        conflicts = decisions.disagreements(review=self.review)
        self.assertEqual([a3.pk], [row["article"].pk for row in conflicts])
        self.assertEqual(
            {"alice": "A", "claude-agent": "R"}, {d.user.username: d.status for d in conflicts[0]["decisions"]}
        )

        with self.subTest(msg="explicit users and unknown users"):
            explicit = decisions.agreement(review=self.review, user_a_id=self.agent.pk, user_b_id=self.human.pk)
            self.assertEqual("claude-agent", explicit["user_a"])
            with self.assertRaises(NotFound):
                decisions.agreement(review=self.review, user_a_id=self.agent.pk, user_b_id=UserFactory().pk)
        with self.subTest(msg="single reviewer cannot be compared"):
            with self.assertRaises(ValidationError):
                decisions.agreement(review=self.review, stage="full_text")

    def test_consolidation_rules(self):
        a1, a2, a3, a4 = self.articles
        third = UserFactory()
        for article, votes in ((a1, "AA"), (a2, "RR"), (a3, "AR"), (a4, "RRA")):
            for user, status in zip((self.human, self.agent, third), votes):
                self.decide(user, article, status)

        result = decisions.consolidate(review=self.review, rule="unanimous", actor=self.human)
        self.assertEqual((2, 2, 2), (result["resolved"], result["unresolved"], result["changed"]))
        self.assertEqual(
            {a1.pk: "A", a2.pk: "R", a3.pk: "U", a4.pk: "U"},
            {a.pk: Article.objects.get(pk=a.pk).status for a in self.articles},
        )

        result = decisions.consolidate(review=self.review, rule="any_include")
        self.assertEqual(4, result["resolved"])
        self.assertEqual(([a3.pk, a4.pk], 2), (result["changed_ids"], result["changed"]))  # a1 and a2 were set
        self.assertEqual(("A", "A"), (Article.objects.get(pk=a3.pk).status, Article.objects.get(pk=a4.pk).status))

        Article.objects.filter(review=self.review).update(status="U")
        result = decisions.consolidate(review=self.review, rule="majority", article_ids=[a3.pk, a4.pk])
        self.assertEqual(([a4.pk], [a3.pk]), (result["resolved_ids"], result["unresolved_ids"]))
        self.assertEqual([a4.pk], result["changed_ids"])
        self.assertEqual("R", Article.objects.get(pk=a4.pk).status)
        with self.assertRaises(ValidationError):
            decisions.consolidate(review=self.review, rule="dictator")

    def test_two_reviewers_chosen_out_of_three(self):
        a1, a2, a3, _a4 = self.articles
        third = UserFactory(username="bob")
        for article, votes in ((a1, "AAR"), (a2, "RAR"), (a3, "AAA")):
            for user, status in zip((self.human, self.agent, third), votes):
                self.decide(user, article, status)
        with self.subTest(msg="every reviewer by default"):
            self.assertEqual(
                {a1.pk, a2.pk}, {row["article"].pk for row in decisions.disagreements(review=self.review)}
            )
        with self.subTest(msg="alice and bob: only where those two differ"):
            pair = {"user_a_id": self.human.pk, "user_b_id": third.pk}
            conflicts = decisions.disagreements(review=self.review, **pair)
            self.assertEqual([a1.pk], [row["article"].pk for row in conflicts])
            self.assertEqual({"alice", "bob"}, {d.user.username for d in conflicts[0]["decisions"]})
            report = decisions.agreement(review=self.review, **pair)
            self.assertEqual(
                ("alice", "bob", 3, 2), (report["user_a"], report["user_b"], report["compared"], report["agreed"])
            )
        with self.subTest(msg="two different reviewers"):
            with self.assertRaisesMessage(ValidationError, "Choose two different reviewers"):
                decisions.agreement(review=self.review, user_a_id=third.pk, user_b_id=third.pk)
        with self.subTest(msg="consolidating the decisions of two of them"):
            result = decisions.consolidate(review=self.review, rule="unanimous", user_ids=[self.agent.pk, third.pk])
            self.assertEqual(([a3.pk], sorted([a1.pk, a2.pk])), (result["resolved_ids"], result["unresolved_ids"]))
            result = decisions.consolidate(
                review=self.review, rule="unanimous", user_ids=[self.human.pk, self.agent.pk]
            )
            self.assertEqual(sorted([a1.pk, a3.pk]), result["resolved_ids"])
            with self.assertRaisesMessage(ValidationError, "at least two reviewers"):
                decisions.consolidate(review=self.review, user_ids=[third.pk])
            with self.assertRaises(NotFound):
                decisions.consolidate(review=self.review, user_ids=[third.pk, UserFactory().pk])

    def test_summary_in_overview(self):
        self.decide(self.agent, self.articles[0], "A")
        self.decide(self.agent, self.articles[1], "A", stage="full_text")
        summary = decisions.summary(self.review)
        self.assertEqual(
            [("title_abstract", {"claude-agent": 1}, 1), ("full_text", {"claude-agent": 1}, 1)],
            [(r["stage"], r["reviewers"], r["articles"]) for r in summary],
        )
        overview = reviews.review_overview(self.review)
        self.assertEqual(2, len(overview["decisions"]))

    def test_legacy_models_removed(self):
        from parsifal.apps.reviews import models

        for name in ("SearchResult", "StudySelection", "Study"):
            self.assertFalse(hasattr(models, name), name)
        self.assertTrue(StudyDecision.objects.model is StudyDecision)
