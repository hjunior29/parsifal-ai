from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from parsifal.apps.accounts.models import Integration
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core import jev
from parsifal.apps.core.exceptions import NotFound, PermissionDenied, UpstreamError, ValidationError
from parsifal.apps.reviews.models import Article, ScreeningResult, ScreeningRun, SelectionCriteria, StudyDecision
from parsifal.apps.reviews.services import agents, ai_screening, decisions
from parsifal.apps.reviews.tests.factories import ArticleFactory, QuestionFactory, ReviewFactory, SourceFactory

MODELS = [
    {"name": "jev-1.13.0", "description": "Stable", "release_date": "2026-08-01"},
    {"name": "jev-1.14.0", "description": "Newest", "release_date": "2026-10-14"},
]


def answer(probabilities_by_question, model="jev-1.13.0"):
    return {
        "model": model,
        "answers": {
            question_id: {"type": "choice", "choice": max(p, key=p.get), "probabilities": p, "confidence": 0.5}
            for question_id, p in probabilities_by_question.items()
        },
    }


def same_answer(probabilities):
    return answer({question_id: probabilities for question_id in ("exclusion_1", "exclusion_2", "exclusion_3")})


EXCLUDE_E2 = same_answer({"E1": 0.02, "E2": 0.95, "none": 0.03})
EXCLUDE_E1 = same_answer({"E1": 0.95, "E2": 0.02, "none": 0.03})
KEEP = same_answer({"E1": 0.05, "E2": 0.05, "none": 0.9})


class AiScreeningTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.other_source = SourceFactory()
        cls.review = ReviewFactory(
            sources=[cls.source, cls.other_source],
            objective="Find studies about screening automation.",
            population="Software engineering researchers",
        )
        cls.owner = cls.review.author
        cls.bot = agents.create_agent(review=cls.review, actor=cls.owner, name="Screener A").agent.user
        cls.other_bot = agents.create_agent(review=cls.review, actor=cls.owner, name="Screener B").agent.user
        QuestionFactory(review=cls.review, question="RQ1: Which tools exist?", order=1)
        QuestionFactory(review=cls.review, question="RQ2: How are they evaluated?", order=2)
        # Listed alphabetically by the review: "Not a primary study" (E1), "Not in English" (E2).
        cls.secondary = SelectionCriteria.objects.create(
            review=cls.review, criteria_type="E", description="Not a primary study"
        )
        cls.english = SelectionCriteria.objects.create(
            review=cls.review, criteria_type="E", description="Not in English"
        )
        SelectionCriteria.objects.create(review=cls.review, criteria_type="I", description="About screening")
        Integration.objects.create(user=cls.owner, provider=Integration.JEV, api_key="fake-key", model="jev-1.13.0")

    def article(self, **kwargs):
        defaults = {"review": self.review, "source": self.source, "abstract": "An abstract."}
        defaults.update(kwargs)
        return ArticleFactory(**defaults)

    def start(self, **kwargs):
        defaults = {"review": self.review, "actor": self.owner, "reviewer_id": self.bot.pk}
        defaults.update(kwargs)
        return ai_screening.start_run(**defaults)

    def step(self, run, responses):
        # One worker, so that the responses are given to the studies in order.
        with (
            mock.patch.object(jev, "evaluate", side_effect=responses) as evaluate,
            mock.patch.object(ai_screening, "WORKERS", 1),
        ):
            results = ai_screening.process_step(run=run, actor=self.owner)
        run.refresh_from_db()
        return results, evaluate

    def decision(self, article, user=None):
        return StudyDecision.objects.get(article=article, user=user or self.bot, stage=StudyDecision.TITLE_ABSTRACT)


class TestRequest(AiScreeningTestCase):
    def test_defaults_come_from_the_review(self):
        context = ai_screening.default_context(self.review)
        self.assertEqual("Find studies about screening automation.", context["objective"])
        self.assertEqual("RQ1: Which tools exist?\nRQ2: How are they evaluated?", context["research_questions"])
        self.assertEqual("Software engineering researchers", context["population"])
        self.assertEqual(
            [
                {"key": "E1", "id": self.secondary.pk, "description": "Not a primary study"},
                {"key": "E2", "id": self.english.pk, "description": "Not in English"},
            ],
            ai_screening.exclusion_options(self.review),
        )

    def test_three_orders_of_the_same_choice_question(self):
        options = ai_screening.exclusion_options(self.review)
        context = ai_screening.default_context(self.review)
        questions = ai_screening.questions(options, context, guidance="")
        self.assertEqual(["exclusion_1", "exclusion_2", "exclusion_3"], list(questions))
        orders = [list(question["criteria"]) for question in questions.values()]
        self.assertEqual([["E1", "E2", "none"], ["E2", "none", "E1"], ["none", "E1", "E2"]], orders)
        first = questions["exclusion_1"]
        self.assertEqual("choice", first["type"])
        self.assertEqual("Not in English", first["criteria"]["E2"])
        self.assertEqual(ai_screening.NONE_DESCRIPTION, first["criteria"]["none"])
        self.assertEqual(
            ["RQ1: Which tools exist?", "RQ2: How are they evaluated?"],
            first["instructions"]["review"]["research_questions"],
        )
        self.assertNotIn("comparison", first["instructions"]["review"])  # empty fields are left out
        self.assertNotIn("guidance", first["instructions"])
        self.assertEqual(list(ai_screening.RULES), first["instructions"]["rules"])
        with_guidance = ai_screening.questions(options, context, guidance="Tertiary studies count as secondary.")
        self.assertEqual(
            "Tertiary studies count as secondary.", with_guidance["exclusion_1"]["instructions"]["guidance"]
        )

    def test_a_single_criterion_gives_two_orders(self):
        options = [{"key": "E1", "id": 1, "description": "x"}]
        self.assertEqual([["E1", "none"], ["none", "E1"]], ai_screening._orders(options))
        self.assertEqual(["exclusion_1", "exclusion_2"], ai_screening.question_ids(options))

    def test_state_sends_title_keywords_and_abstract_only(self):
        article = self.article(
            title=" Title ", author="Doe, J.", journal="Venue", author_keywords="", keywords="k1; k2", abstract="Text"
        )
        self.assertEqual({"title": "Title", "keywords": "k1; k2", "abstract": "Text"}, ai_screening.state(article))
        self.assertIsNone(ai_screening.state(self.article(title="", abstract="  ")))
        self.assertEqual({"title": "Only"}, ai_screening.state(self.article(title="Only", abstract=None)))

    def test_combine_uses_one_minus_none(self):
        options = ai_screening.exclusion_options(self.review)
        # Two criteria split the probability: "none" wins the choice, yet exclusion is likely.
        response = answer(
            {
                "exclusion_1": {"E1": 0.33, "E2": 0.32, "none": 0.35},
                "exclusion_2": {"E1": 0.40, "E2": 0.30, "none": 0.30},
                "exclusion_3": {"E1": 0.26, "E2": 0.34, "none": 0.40},
            }
        )
        probabilities, p_exclude, best = ai_screening.combine(response, options)
        self.assertEqual({"E1": 0.33, "E2": 0.32, "none": 0.35}, probabilities)
        self.assertEqual((0.65, "E1"), (p_exclude, best))
        with self.assertRaisesMessage(jev.JevError, "did not answer"):
            ai_screening.combine({"answers": {}}, options)
        with self.assertRaisesMessage(jev.JevError, "not numbers"):
            ai_screening.combine({"answers": {"exclusion_1": {"probabilities": {"E1": "x"}}}}, options)


class TestReviewers(AiScreeningTestCase):
    def test_the_main_author_may_screen_as_anyone_in_the_review(self):
        choices = ai_screening.reviewer_choices(self.review, self.owner)
        self.assertEqual({self.owner, self.bot, self.other_bot}, set(choices))
        self.assertEqual({self.bot.pk, self.other_bot.pk}, ai_screening.agent_ids(self.review))
        self.assertEqual(self.other_bot, ai_screening.get_reviewer(self.review, self.owner, str(self.other_bot.pk)))

    def test_anyone_else_only_as_themselves(self):
        self.assertEqual([self.bot], ai_screening.reviewer_choices(self.review, self.bot))
        self.assertEqual(self.bot, ai_screening.get_reviewer(self.review, self.bot, self.bot.pk))
        with self.assertRaises(PermissionDenied):
            ai_screening.get_reviewer(self.review, self.bot, self.owner.pk)
        with self.assertRaises(NotFound):
            ai_screening.get_reviewer(self.review, self.owner, UserFactory().pk)
        with self.assertRaisesMessage(ValidationError, "Choose the reviewer"):
            ai_screening.get_reviewer(self.review, self.owner, "")


class TestStartRun(AiScreeningTestCase):
    def test_requirements(self):
        self.article()
        with self.assertRaisesMessage(ValidationError, "Settings → Integrations"):
            self.start(actor=UserFactory())
        with self.assertRaisesMessage(ValidationError, "Choose the reviewer"):
            self.start(reviewer_id=None)
        with self.assertRaisesMessage(ValidationError, "between 0.5 and 0.99"):
            self.start(threshold=0.3)
        with self.assertRaisesMessage(ValidationError, "must be a number"):
            self.start(threshold="high")
        with self.assertRaisesMessage(ValidationError, "An exclusion run takes threshold, not accept_threshold"):
            self.start(accept_threshold=0.9)
        with self.assertRaises(ValidationError):
            self.start(guidance="x" * (ai_screening.GUIDANCE_LENGTH + 1))
        with self.assertRaises(NotFound):
            self.start(source_id=SourceFactory().pk)
        with self.assertRaisesMessage(ValidationError, "no studies with these statuses"):
            self.start(source_id=self.other_source.pk)
        with self.assertRaisesMessage(ValidationError, "no studies with these statuses"):
            self.start(statuses=["A", "D"])
        with self.assertRaisesMessage(ValidationError, "Unknown status X"):
            self.start(statuses=["U", "X"])
        with self.assertRaisesMessage(ValidationError, "Choose the statuses"):
            self.start(statuses=[])
        empty = ReviewFactory(author=self.owner)
        with self.assertRaisesMessage(ValidationError, "no exclusion criteria"):
            self.start(review=empty, reviewer_id=self.owner.pk)
        self.assertFalse(ScreeningRun.objects.exists())

    def test_model_is_the_default_or_one_jev_lists(self):
        self.article()
        self.assertEqual("jev-1.13.0", self.start().model)
        with mock.patch.object(jev, "list_models", return_value=MODELS):
            self.assertEqual("jev-1.14.0", self.start(model="jev-1.14.0").model)
            with self.assertRaisesMessage(ValidationError, "does not list the model 'jev-9'"):
                self.start(model="jev-9")
        with mock.patch.object(jev, "list_models", side_effect=jev.JevError("Could not reach Jev (Timeout).")):
            with self.assertRaises(UpstreamError):
                self.start(model="jev-1.14.0")

    def test_opens_a_run_with_a_snapshot_and_the_reviewer(self):
        first = self.article()
        self.article(source=self.other_source)
        accepted = self.article(status=Article.ACCEPTED)
        duplicated = self.article(status=Article.DUPLICATED)
        context = dict(ai_screening.default_context(self.review), objective="  Edited objective  ")
        run = self.start(context=context, guidance="Be strict.", threshold="0.85", source_id=str(self.source.pk))

        self.assertEqual((ScreeningRun.RUNNING, 1, "jev-1.13.0"), (run.status, run.total, run.model))
        self.assertEqual((self.bot, self.owner), (run.reviewer, run.started_by))
        self.assertEqual([(first.pk, "U")], list(run.results.values_list("article_id", "previous_status")))
        self.assertEqual("Edited objective", run.parameters["context"]["objective"])
        self.assertEqual(
            ("Be strict.", 0.85, self.source.pk, ["R", "U"]),
            tuple(run.parameters[k] for k in ("guidance", "threshold", "source_id", "statuses")),
        )
        self.assertEqual(["E1", "E2"], [option["key"] for option in run.parameters["criteria"]])

        with self.subTest(msg="the statuses chosen pick the studies"):
            chosen = self.start(statuses=["d", "A"], source_id=self.source.pk)
            self.assertEqual(["A", "D"], chosen.parameters["statuses"])
            self.assertEqual(
                {accepted.pk: "A", duplicated.pk: "D"},
                dict(chosen.results.values_list("article_id", "previous_status")),
            )

        with self.subTest(msg="context fields left out take the review's values"):
            partial = self.start(context={"objective": "Only this changed", "population": None})
            self.assertEqual("Only this changed", partial.parameters["context"]["objective"])
            self.assertEqual("Software engineering researchers", partial.parameters["context"]["population"])

        with self.subTest(msg="a new run closes a run left behind"):
            run.refresh_from_db()
            self.assertEqual(ScreeningRun.CANCELLED, run.status)
            self.assertFalse(run.results.exists())

        with self.subTest(msg="every status"):
            self.assertEqual(4, self.start(statuses=["U", "R", "A", "D"]).total)


class TestProcessStep(AiScreeningTestCase):
    def test_rejects_above_the_threshold_and_records_every_decision(self):
        excluded = self.article(title="Excluded")
        kept = self.article(title="Kept")
        run = self.start()

        results, evaluate = self.step(run, [EXCLUDE_E2, KEEP])

        self.assertEqual(2, evaluate.call_count)
        call = evaluate.call_args_list[0]
        self.assertEqual(("fake-key",), call.args)
        self.assertEqual("jev-1.13.0", call.kwargs["model"])
        self.assertEqual(["exclusion_1", "exclusion_2", "exclusion_3"], list(call.kwargs["questions"]))
        self.assertEqual(ScreeningRun.FINISHED, run.status)
        self.assertEqual(
            {
                "id": run.pk,
                "phase": "exclusion",
                "status": "finished",
                "total": 2,
                "error": "",
                "excluded": 1,
                "passed": 1,
                "included": 0,
                "undecided": 0,
                "failed": 0,
                "processed": 2,
            },
            ai_screening.progress(run),
        )

        excluded.refresh_from_db()
        self.assertEqual(
            (Article.REJECTED, self.english, self.bot),
            (excluded.status, excluded.selection_criteria, excluded.updated_by),
        )
        decision = self.decision(excluded)
        self.assertEqual(("R", self.english), (decision.status, decision.selection_criteria))
        self.assertIn("E2, p(exclude) = 0.97", decision.comments)
        result = ScreeningResult.objects.get(run=run, article=excluded)
        self.assertEqual(
            (ScreeningResult.EXCLUDED, 0.97, self.english, "jev-1.13.0"),
            (result.outcome, result.p_exclude, result.selection_criteria, result.model),
        )

        kept.refresh_from_db()
        self.assertEqual((Article.UNCLASSIFIED, None), (kept.status, kept.selection_criteria))
        decision = self.decision(kept)
        self.assertEqual(("U", None), (decision.status, decision.selection_criteria))
        self.assertIn("no exclusion criterion, p(exclude) = 0.10", decision.comments)
        self.assertEqual([excluded.pk, kept.pk], [r.article_id for r in results])

    def test_screening_again_as_the_same_reviewer_rewrites_its_decisions(self):
        rejected_then_kept = self.article(title="A")
        kept_then_rejected = self.article(title="B")
        rejected_twice = self.article(title="C")
        self.step(self.start(), [EXCLUDE_E2, KEEP, EXCLUDE_E2])

        second = self.start()
        self.assertEqual(
            {rejected_then_kept.pk: "R", kept_then_rejected.pk: "U", rejected_twice.pk: "R"},
            dict(second.results.values_list("article_id", "previous_status")),
        )  # nothing is skipped
        self.step(second, [KEEP, EXCLUDE_E1, EXCLUDE_E1])

        for article, status, criteria in (
            (rejected_then_kept, Article.UNCLASSIFIED, None),
            (kept_then_rejected, Article.REJECTED, self.secondary),
            (rejected_twice, Article.REJECTED, self.secondary),
        ):
            with self.subTest(article=article.title):
                article.refresh_from_db()
                self.assertEqual((status, criteria), (article.status, article.selection_criteria))
                decision = self.decision(article)
                self.assertEqual((status, criteria), (decision.status, decision.selection_criteria))
                self.assertIn(f"run {second.pk}", decision.comments)
        self.assertEqual(3, StudyDecision.objects.filter(user=self.bot).count())

    def test_another_reviewer_screens_the_same_studies_without_changing_the_first_ones_rejections(self):
        rejected_then_kept = self.article(title="A")
        rejected_twice = self.article(title="B")
        kept_then_rejected = self.article(title="C")
        self.step(self.start(), [EXCLUDE_E2, EXCLUDE_E2, KEEP])

        run = self.start(reviewer_id=self.other_bot.pk)
        self.assertEqual(3, run.total)  # the studies the first reviewer rejected are sent too
        self.step(run, [KEEP, EXCLUDE_E1, EXCLUDE_E1])

        for article, status, criteria, updated_by, first, second in (
            (rejected_then_kept, Article.REJECTED, self.english, self.bot, "R", "U"),
            (rejected_twice, Article.REJECTED, self.english, self.bot, "R", "R"),
            (kept_then_rejected, Article.REJECTED, self.secondary, self.other_bot, "U", "R"),
        ):
            with self.subTest(article=article.title):
                article.refresh_from_db()
                self.assertEqual(
                    (status, criteria, updated_by), (article.status, article.selection_criteria, article.updated_by)
                )
                self.assertEqual(first, self.decision(article).status)  # each reviewer keeps its own decision
                self.assertEqual(second, self.decision(article, self.other_bot).status)
        agreement = decisions.agreement(review=self.review, user_a_id=self.bot.pk, user_b_id=self.other_bot.pk)
        self.assertEqual((3, 1), (agreement["compared"], agreement["agreed"]))

    def test_accepted_and_duplicated_studies_keep_their_status(self):
        accepted = self.article(status=Article.ACCEPTED, updated_by=self.bot)
        duplicated = self.article(status=Article.DUPLICATED)
        run = self.start(statuses=["A", "D"])
        self.step(run, [EXCLUDE_E2, KEEP])
        accepted.refresh_from_db()
        duplicated.refresh_from_db()
        self.assertEqual((Article.ACCEPTED, None), (accepted.status, accepted.selection_criteria))
        self.assertEqual(Article.DUPLICATED, duplicated.status)
        self.assertEqual(("R", "U"), (self.decision(accepted).status, self.decision(duplicated).status))
        self.assertEqual((1, 1), (ai_screening.progress(run)["excluded"], ai_screening.progress(run)["passed"]))

    def test_the_owner_can_screen_as_themselves(self):
        article = self.article()
        run = self.start(reviewer_id=self.owner.pk)
        self.step(run, [EXCLUDE_E2])
        article.refresh_from_db()
        self.assertEqual((Article.REJECTED, self.owner), (article.status, article.updated_by))
        self.assertEqual("R", self.decision(article, self.owner).status)

    def test_threshold_is_inclusive_and_configurable(self):
        article = self.article()
        self.assertEqual(0.9, self.start().parameters["threshold"])
        run = self.start(threshold=0.97)
        self.step(run, [EXCLUDE_E2])
        article.refresh_from_db()
        self.assertEqual(Article.REJECTED, article.status)

    def test_runs_in_steps(self):
        for _ in range(3):
            self.article()
        run = self.start()
        with mock.patch.object(jev, "evaluate", return_value=KEEP):
            first = ai_screening.process_step(run=run, actor=self.owner, size=2)
            run.refresh_from_db()
            self.assertEqual((2, ScreeningRun.RUNNING), (len(first), run.status))
            ai_screening.process_step(run=run, actor=self.owner, size=2)
            run.refresh_from_db()
        self.assertEqual(ScreeningRun.FINISHED, run.status)
        self.assertEqual(3, ai_screening.progress(run)["passed"])
        self.assertEqual([], ai_screening.process_step(run=run, actor=self.owner))  # finished runs do nothing
        with self.assertRaisesMessage(ValidationError, "between 1 and 50"):
            ai_screening.process_step(run=run, actor=self.owner, size=51)

    def test_errors_about_one_study_do_not_stop_the_run(self):
        no_text = self.article(title="", abstract="")
        too_long = self.article()
        fine = self.article()
        run = self.start()
        self.step(run, [jev.JevError("Jev answered 400: max_tokens_exceeded", status=400), EXCLUDE_E2])

        self.assertEqual(ScreeningRun.FINISHED, run.status)
        outcomes = dict(run.results.values_list("article_id", "outcome"))
        self.assertEqual({no_text.pk: "error", too_long.pk: "error", fine.pk: "excluded"}, outcomes)
        self.assertIn("max_tokens_exceeded", run.results.get(article=too_long).error)
        too_long.refresh_from_db()
        self.assertEqual(Article.UNCLASSIFIED, too_long.status)
        self.assertFalse(StudyDecision.objects.filter(article=too_long).exists())

    def test_a_rejected_key_interrupts_the_run_until_it_is_continued(self):
        first = self.article()
        self.article()
        run = self.start()
        error = jev.JevError("Jev rejected the API key. Update it in Settings → Integrations.", status=401, fatal=True)
        self.assertEqual([], self.step(run, [error, error])[0])
        self.assertEqual((ScreeningRun.RUNNING, None), (run.status, run.last_step_at))
        self.assertIn("rejected the API key", run.error)
        self.assertEqual(2, run.results.filter(outcome=ScreeningResult.PENDING).count())
        self.assertEqual(run, ai_screening.unfinished_run(self.review))
        self.assertFalse(ai_screening.is_active(run))
        first.refresh_from_db()
        self.assertEqual(Article.UNCLASSIFIED, first.status)

        self.step(run, [EXCLUDE_E2, KEEP])  # continued with a key that works
        self.assertEqual((ScreeningRun.FINISHED, ""), (run.status, run.error))
        self.assertEqual((1, 1), (ai_screening.progress(run)["excluded"], ai_screening.progress(run)["passed"]))
        self.assertIsNone(ai_screening.unfinished_run(self.review))

    def test_jev_unavailable_keeps_the_studies_for_later(self):
        for _ in range(3):
            self.article()
        run = self.start()
        unavailable = jev.JevError("Jev answered 529: overloaded", status=529)
        with mock.patch.object(jev, "evaluate", side_effect=[unavailable, unavailable]):
            self.assertEqual([], ai_screening.process_step(run=run, actor=self.owner, size=2))
        run.refresh_from_db()
        self.assertEqual((ScreeningRun.RUNNING, "Jev answered 529: overloaded"), (run.status, run.error))
        self.assertEqual((0, 0), (ai_screening.progress(run)["processed"], ai_screening.progress(run)["failed"]))
        self.assertEqual(3, run.results.filter(outcome=ScreeningResult.PENDING).count())

        with self.subTest(msg="a partly unavailable step goes on; the unavailable study is sent again"):
            with mock.patch.object(jev, "evaluate", side_effect=[KEEP, unavailable]):
                recorded = ai_screening.process_step(run=run, actor=self.owner, size=2)
            run.refresh_from_db()
            self.assertEqual((1, ""), (len(recorded), run.error))
            self.assertEqual(2, run.results.filter(outcome=ScreeningResult.PENDING).count())
            self.step(run, [KEEP, KEEP])
            self.assertEqual((ScreeningRun.FINISHED, 3), (run.status, ai_screening.progress(run)["passed"]))

    def test_a_study_classified_meanwhile_keeps_its_status(self):
        accepted = self.article()
        restored = self.article()
        self.step(self.start(), [KEEP, EXCLUDE_E2])
        run = self.start()  # takes restored as "rejected by this reviewer"
        Article.objects.filter(pk=accepted.pk).update(status=Article.ACCEPTED)
        Article.objects.filter(pk=restored.pk).update(updated_by=self.owner)  # the owner reviewed it meanwhile
        self.step(run, [EXCLUDE_E2, KEEP])
        accepted.refresh_from_db()
        restored.refresh_from_db()
        self.assertEqual(Article.ACCEPTED, accepted.status)
        self.assertEqual(Article.REJECTED, restored.status)
        self.assertEqual(("R", "U"), (self.decision(accepted).status, self.decision(restored).status))

    def test_a_criterion_deleted_meanwhile_is_reported(self):
        article = self.article()
        run = self.start()
        self.english.delete()
        self.step(run, [EXCLUDE_E2])
        result = run.results.get()
        self.assertEqual(ScreeningResult.ERROR, result.outcome)
        self.assertIn("E2 was deleted", result.error)
        article.refresh_from_db()
        self.assertEqual(Article.UNCLASSIFIED, article.status)

    def test_an_unfinished_run_is_continued_or_discarded(self):
        self.article()
        self.article()
        run = self.start()
        self.assertIsNone(run.last_step_at)
        self.assertEqual(run, ai_screening.unfinished_run(self.review))  # page closed before the first step
        with mock.patch.object(jev, "evaluate", return_value=KEEP):
            ai_screening.process_step(run=run, actor=self.owner, size=1)
        run.refresh_from_db()
        self.assertTrue(ai_screening.is_active(run))  # being driven right now
        ScreeningRun.objects.filter(pk=run.pk).update(last_step_at=timezone.now() - timedelta(minutes=5))
        run.refresh_from_db()
        self.assertFalse(ai_screening.is_active(run))

        with self.subTest(msg="continued with the parameters it started with"):
            with mock.patch.object(jev, "evaluate", return_value=KEEP) as evaluate:
                ai_screening.process_step(run=run, actor=self.owner, size=8)
            self.assertEqual(run.model, evaluate.call_args.kwargs["model"])
            run.refresh_from_db()
            self.assertEqual((ScreeningRun.FINISHED, 2), (run.status, ai_screening.progress(run)["processed"]))

        with self.subTest(msg="a new run discards an unfinished one"):
            left = self.start()
            self.start()
            left.refresh_from_db()
            self.assertEqual(ScreeningRun.CANCELLED, left.status)
            self.assertFalse(left.results.filter(outcome=ScreeningResult.PENDING).exists())


class TestScope(AiScreeningTestCase):
    def test_counts_per_source_and_status(self):
        self.article()
        self.article()
        self.article(status=Article.ACCEPTED)
        self.article(source=self.other_source)
        self.step(self.start(source_id=self.source.pk, statuses=["U"]), [KEEP, EXCLUDE_E2])
        self.assertEqual(
            {
                "": {"A": 1, "R": 1, "U": 2, "D": 0},
                str(self.source.pk): {"A": 1, "R": 1, "U": 1, "D": 0},
                str(self.other_source.pk): {"A": 0, "R": 0, "U": 1, "D": 0},
            },
            ai_screening.scope_counts(self.review),
        )
        self.assertEqual(self.bot.pk, ai_screening.last_reviewer_id(self.review))

    def test_clean_statuses(self):
        self.assertEqual(["R", "U"], ai_screening.clean_statuses(None))
        self.assertEqual(["A", "R", "U", "D"], ai_screening.clean_statuses(["u", "D", " r ", "A", "U"]))
        self.assertEqual(["U"], ai_screening.clean_statuses("U"))

    def test_deleting_the_reviewer_agent_deletes_its_runs_and_decisions(self):
        article = self.article()
        run = self.start()
        self.step(run, [EXCLUDE_E2])
        deleted = agents.delete_agent(review=self.review, actor=self.owner, agent_id=self.bot.pk)
        self.assertEqual(1, deleted["decisions"])
        self.assertFalse(ScreeningRun.objects.filter(pk=run.pk).exists())
        article.refresh_from_db()
        self.assertEqual((Article.REJECTED, None), (article.status, article.updated_by))


def yes_no(probabilities_by_question, model="jev-1.13.0"):
    return {
        "model": model,
        "answers": {question_id: {"type": "noul", "noul": p} for question_id, p in probabilities_by_question.items()},
    }


def inclusion_answer(by_criterion, model="jev-1.13.0"):
    """The same probability of yes (the study meets it) in both orders: {"I1": p, …}."""
    return yes_no(
        {f"inclusion_{key.lower()}_{order}": p for key, p in by_criterion.items() for order in (1, 2)}, model=model
    )


BOTH_MET = inclusion_answer({"I1": 0.95, "I2": 0.97})
I1_NOT_MET = inclusion_answer({"I1": 0.06, "I2": 0.90})
I2_UNSURE = inclusion_answer({"I1": 0.96, "I2": 0.40})


class TestInclusion(AiScreeningTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Listed alphabetically by the review: "About screening" (I1), "Implemented tool" (I2).
        cls.about = cls.review.selectioncriteria_set.get(criteria_type="I")
        cls.tool = SelectionCriteria.objects.create(
            review=cls.review, criteria_type="I", description="Implemented tool"
        )

    def start(self, **kwargs):
        return super().start(**{"phase": "inclusion", **kwargs})

    def test_one_yes_no_question_per_criterion_in_both_orders(self):
        options = ai_screening.inclusion_options(self.review)
        self.assertEqual(
            [
                {"key": "I1", "id": self.about.pk, "description": "About screening"},
                {"key": "I2", "id": self.tool.pk, "description": "Implemented tool"},
            ],
            options,
        )
        questions = ai_screening.inclusion_questions(options, ai_screening.default_context(self.review), "Be strict.")
        self.assertEqual(["inclusion_i1_1", "inclusion_i1_2", "inclusion_i2_1", "inclusion_i2_2"], list(questions))
        self.assertEqual(
            [["true", "false"], ["false", "true"]],
            [list(questions[f"inclusion_i2_{order}"]["criteria"]) for order in (1, 2)],
        )
        question = questions["inclusion_i2_1"]
        self.assertEqual("noul", question["type"])
        self.assertEqual(
            {
                "true": "The study meets the inclusion criterion: Implemented tool",
                "false": "The study does not meet the inclusion criterion: Implemented tool",
            },
            question["criteria"],
        )
        body = question["instructions"]
        self.assertEqual(
            ("I2: Implemented tool", ai_screening.INCLUSION_TASK, list(ai_screening.INCLUSION_RULES), "Be strict."),
            (body["criterion"], body["task"], body["rules"], body["guidance"]),
        )
        self.assertEqual("Find studies about screening automation.", body["review"]["objective"])

    def test_combine_averages_the_orders_and_takes_the_weakest_criterion(self):
        options = ai_screening.inclusion_options(self.review)
        response = yes_no({"inclusion_i1_1": 1.0, "inclusion_i1_2": 1.0, "inclusion_i2_1": 0.9, "inclusion_i2_2": 0.7})
        self.assertEqual(({"I1": 1.0, "I2": 0.8}, "I2"), ai_screening.combine_inclusion(response, options))
        with self.subTest(msg="an order left unanswered is not counted"):
            response = yes_no({"inclusion_i1_1": 0.9, "inclusion_i2_2": 0.5})
            self.assertEqual(({"I1": 0.9, "I2": 0.5}, "I2"), ai_screening.combine_inclusion(response, options))
        with self.assertRaisesMessage(jev.JevError, "did not answer the question about I2"):
            ai_screening.combine_inclusion(yes_no({"inclusion_i1_1": 1.0}), options)
        with self.assertRaisesMessage(jev.JevError, "not numbers"):
            ai_screening.combine_inclusion(yes_no({"inclusion_i1_1": "yes", "inclusion_i2_1": 1.0}), options)

    def test_thresholds(self):
        self.article()
        run = self.start(accept_threshold="0.95", reject_threshold=0.8)
        self.assertEqual(
            (0.95, 0.8, False, 2),
            (
                run.parameters["accept_threshold"],
                run.parameters["reject_threshold"],
                "threshold" in run.parameters,
                run.parameters["orders"],
            ),
        )
        defaults = self.start()
        self.assertEqual(
            (0.9, 0.9), (defaults.parameters["accept_threshold"], defaults.parameters["reject_threshold"])
        )
        with self.assertRaisesMessage(ValidationError, "accept threshold must be between 0.5 and 0.99"):
            self.start(accept_threshold=0.3)
        with self.assertRaisesMessage(ValidationError, "reject threshold must be a number"):
            self.start(reject_threshold="")
        with self.assertRaisesMessage(ValidationError, "takes accept_threshold and reject_threshold, not threshold"):
            self.start(threshold=0.9)

        with self.subTest(msg="the reject threshold may go below 0.5, down to 1 - accept threshold"):
            low = self.start(accept_threshold=0.85, reject_threshold=0.2)
            self.assertEqual(0.2, low.parameters["reject_threshold"])
            self.assertEqual(
                0.15, self.start(accept_threshold=0.85, reject_threshold=0.15).parameters["reject_threshold"]
            )
            with self.assertRaisesMessage(
                ValidationError,
                "With the accept threshold at 0.85, the reject threshold must be at least 0.15: at 0.15 every study "
                "that is not accepted is rejected.",
            ):
                self.start(accept_threshold=0.85, reject_threshold=0.1)
            with self.assertRaisesMessage(ValidationError, "reject threshold must be between 0.01 and 0.99"):
                self.start(accept_threshold=0.99, reject_threshold=0)
            with self.assertRaisesMessage(ValidationError, "threshold must be between 0.5 and 0.99"):
                super().start(threshold=0.2)  # exclusion keeps its range

    def test_accepts_when_every_criterion_is_met_rejects_when_one_is_not_and_leaves_the_rest(self):
        accepted = self.article(title="Accepted")
        rejected = self.article(title="Rejected")
        undecided = self.article(title="Undecided")
        self.article(title="Out already", status=Article.REJECTED, updated_by=self.owner)
        run = self.start()
        self.assertEqual(("inclusion", 3), (run.phase, run.total))  # unclassified and accepted, by default
        self.assertEqual((["A", "U"], "keep_undecided"), (run.parameters["statuses"], run.parameters["rule"]))

        self.step(run, [BOTH_MET, I1_NOT_MET, I2_UNSURE])

        progress = ai_screening.progress(run)
        self.assertEqual(
            ("finished", 1, 1, 1, 0),
            tuple(progress[k] for k in ("status", "included", "excluded", "undecided", "passed")),
        )
        for article, status, criteria, decision_status, comment in (
            (accepted, Article.ACCEPTED, None, "A", "meets every inclusion criterion — meets: I1 0.95, I2 0.97."),
            (rejected, Article.REJECTED, self.about, "R", "I1 not met (meet 0.06) — meets: I1 0.06, I2 0.90."),
            (
                undecided,
                Article.UNCLASSIFIED,
                None,
                "U",
                "undecided, weakest I2 (meet 0.40) — meets: I1 0.96, I2 0.40.",
            ),
        ):
            with self.subTest(article=article.title):
                article.refresh_from_db()
                self.assertEqual((status, criteria), (article.status, article.selection_criteria))
                decision = self.decision(article)
                self.assertEqual((decision_status, criteria), (decision.status, decision.selection_criteria))
                self.assertEqual(f"Include with AI (run {run.pk}, jev-1.13.0): {comment}", decision.comments)
        result = run.results.get(article=undecided)
        self.assertEqual(
            (ScreeningResult.UNDECIDED, 0.4, 0.6, {"I1": 0.96, "I2": 0.4}),
            (result.outcome, result.p_include, result.p_exclude, result.probabilities),
        )
        rejection = run.results.get(article=rejected)
        self.assertEqual(
            (0.06, 0.94, self.about.pk), (rejection.p_include, rejection.p_exclude, rejection.selection_criteria_id)
        )

    def test_each_threshold_decides_its_side(self):
        articles = [self.article(title=title) for title in ("Met 0.93", "Not met 0.15", "Met 0.97", "Not met 0.05")]
        run = self.start(accept_threshold=0.95, reject_threshold=0.85)
        answers = [inclusion_answer({"I1": p, "I2": 0.99}) for p in (0.93, 0.15, 0.97, 0.05)]
        self.step(run, answers)
        self.assertEqual(
            ["undecided", "excluded", "included", "excluded"],
            [run.results.get(article=article).outcome for article in articles],
        )
        lenient = self.start(accept_threshold=0.9, reject_threshold=0.9, statuses=["U", "A", "R"])
        self.step(lenient, answers)
        self.assertEqual(
            ["included", "undecided", "included", "excluded"],
            [lenient.results.get(article=article).outcome for article in articles],
        )
        # Rejecting what is not clearly in: at 1 - accept threshold nothing is left undecided.
        strict = self.start(accept_threshold=0.95, reject_threshold=0.05, statuses=["U", "A", "R"])
        self.step(strict, answers)
        self.assertEqual(
            ["excluded", "excluded", "included", "excluded"],
            [strict.results.get(article=article).outcome for article in articles],
        )
        low = self.start(accept_threshold=0.85, reject_threshold=0.2, statuses=["U", "A", "R"])
        self.step(low, [inclusion_answer({"I1": p, "I2": 0.99}) for p in (0.80, 0.82, 0.85, 0.5)])
        self.assertEqual(
            ["excluded", "undecided", "included", "excluded"],  # 0.80 is at the threshold: rejected
            [low.results.get(article=article).outcome for article in articles],
        )

    def test_a_criterion_clearly_met_does_not_make_up_for_a_weak_one(self):
        article = self.article()
        run = self.start()
        self.step(run, [inclusion_answer({"I1": 1.0, "I2": 0.8})])  # average 0.9
        article.refresh_from_db()
        self.assertEqual((Article.UNCLASSIFIED, "undecided"), (article.status, run.results.get().outcome))

    def test_status_changes_only_for_unclassified_studies_and_the_reviewers_own(self):
        own = self.article(title="Accepted by this reviewer before")
        theirs = self.article(title="Accepted by the owner", status=Article.ACCEPTED, updated_by=self.owner)
        rejected = self.article(title="Rejected by this reviewer in phase 1")
        duplicated = self.article(title="Duplicate", status=Article.DUPLICATED)
        self.step(self.start(statuses=["U"]), [BOTH_MET, I1_NOT_MET])
        own.refresh_from_db()
        self.assertEqual(Article.ACCEPTED, own.status)

        run = self.start(statuses=["U", "R", "A", "D"])
        self.assertEqual(4, run.total)
        self.step(run, [I2_UNSURE, I1_NOT_MET, BOTH_MET, I1_NOT_MET])
        for article, status, decision_status in (
            (own, Article.UNCLASSIFIED, "U"),  # its own acceptance, undecided now: back to unclassified
            (theirs, Article.ACCEPTED, "R"),  # someone else's: kept, the reviewer's decision recorded
            (rejected, Article.ACCEPTED, "A"),  # its own rejection, accepted now
            (duplicated, Article.DUPLICATED, "R"),
        ):
            with self.subTest(article=article.title):
                article.refresh_from_db()
                self.assertEqual(status, article.status)
                self.assertEqual(decision_status, self.decision(article).status)

    def test_requirements(self):
        self.article()
        with self.assertRaisesMessage(ValidationError, "phase must be exclusion or inclusion"):
            self.start(phase="maybe")
        no_inclusion = ReviewFactory(author=self.owner, sources=[self.source])
        SelectionCriteria.objects.create(review=no_inclusion, criteria_type="E", description="Out")
        ArticleFactory(review=no_inclusion, source=self.source)
        with self.assertRaisesMessage(ValidationError, "no inclusion criteria"):
            self.start(review=no_inclusion, reviewer_id=self.owner.pk)
        self.assertEqual(["A", "U"], ai_screening.clean_statuses(None, "inclusion"))
