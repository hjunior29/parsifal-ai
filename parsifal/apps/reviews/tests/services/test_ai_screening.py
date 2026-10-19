from unittest import mock

from django.test import TestCase

from parsifal.apps.accounts.models import Integration
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core import jev
from parsifal.apps.core.exceptions import NotFound, ValidationError
from parsifal.apps.reviews.models import Article, ReviewAgent, ScreeningResult, ScreeningRun, SelectionCriteria
from parsifal.apps.reviews.services import agents, ai_screening
from parsifal.apps.reviews.tests.factories import ArticleFactory, QuestionFactory, ReviewFactory, SourceFactory


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
        defaults = {"review": self.review, "actor": self.owner, "context": ai_screening.default_context(self.review)}
        defaults.update(kwargs)
        return ai_screening.start_run(**defaults)

    def step(self, run, responses):
        with mock.patch.object(jev, "evaluate", side_effect=responses) as evaluate:
            results = ai_screening.process_step(run=run, actor=self.owner)
        run.refresh_from_db()
        return results, evaluate


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


class TestStartRun(AiScreeningTestCase):
    def test_requirements(self):
        self.article()
        with self.assertRaisesMessage(ValidationError, "Settings → Integrations"):
            self.start(actor=UserFactory())
        with self.assertRaisesMessage(ValidationError, "between 0.5 and 0.99"):
            self.start(threshold=0.3)
        with self.assertRaisesMessage(ValidationError, "must be a number"):
            self.start(threshold="high")
        with self.assertRaises(ValidationError):
            self.start(guidance="x" * (ai_screening.GUIDANCE_LENGTH + 1))
        with self.assertRaises(NotFound):
            self.start(source_id=SourceFactory().pk)
        with self.assertRaisesMessage(ValidationError, "no unclassified studies"):
            self.start(source_id=self.other_source.pk)
        empty = ReviewFactory(author=self.owner)
        with self.assertRaisesMessage(ValidationError, "no exclusion criteria"):
            self.start(review=empty, context={})
        self.assertFalse(ScreeningRun.objects.exists())

    def test_opens_a_run_with_a_snapshot_and_the_jev_agent(self):
        first = self.article()
        self.article(source=self.other_source)
        self.article(status=Article.ACCEPTED)
        context = dict(ai_screening.default_context(self.review), objective="  Edited objective  ")
        run = self.start(context=context, guidance="Be strict.", threshold="0.85", source_id=str(self.source.pk))

        self.assertEqual((ScreeningRun.RUNNING, 1, "jev-1.13.0"), (run.status, run.total, run.model))
        self.assertEqual([first.pk], list(run.results.values_list("article_id", flat=True)))
        self.assertEqual("Edited objective", run.parameters["context"]["objective"])
        self.assertEqual(
            ("Be strict.", 0.85, self.source.pk),
            tuple(run.parameters[k] for k in ("guidance", "threshold", "source_id")),
        )
        self.assertEqual(["E1", "E2"], [option["key"] for option in run.parameters["criteria"]])

        agent = ReviewAgent.objects.get(review=self.review, kind=ReviewAgent.JEV)
        self.assertEqual((agent.user, "Jev"), (run.agent, agent.name))
        self.assertIn(agent.user, self.review.co_authors.all())
        self.assertFalse(agent.user.has_usable_password())
        self.assertFalse(agent.user.api_tokens.exists())
        with self.assertRaisesMessage(ValidationError, "does not use API tokens"):
            agents.new_token(review=self.review, actor=self.owner, agent_id=agent.user_id)

        with self.subTest(msg="a new run reuses the agent and closes a run left behind"):
            second = self.start()
            run.refresh_from_db()
            self.assertEqual(ScreeningRun.CANCELLED, run.status)
            self.assertFalse(run.results.exists())
            self.assertEqual(agent.user, second.agent)
            self.assertEqual(2, second.total)


class TestProcessStep(AiScreeningTestCase):
    def test_rejects_above_the_threshold_and_passes_the_rest(self):
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
                "status": "finished",
                "total": 2,
                "error": "",
                "excluded": 1,
                "passed": 1,
                "failed": 0,
                "processed": 2,
            },
            ai_screening.progress(run),
        )

        excluded.refresh_from_db()
        jev_user = run.agent
        self.assertEqual(
            (Article.REJECTED, self.english, jev_user),
            (excluded.status, excluded.selection_criteria, excluded.updated_by),
        )
        decision = excluded.decisions.get()
        self.assertEqual((jev_user, "R", self.english), (decision.user, decision.status, decision.selection_criteria))
        self.assertIn("E2, p(exclude) = 0.97", decision.comments)
        result = ScreeningResult.objects.get(run=run, article=excluded)
        self.assertEqual(
            (ScreeningResult.EXCLUDED, 0.97, self.english, "jev-1.13.0"),
            (result.outcome, result.p_exclude, result.selection_criteria, result.model),
        )

        kept.refresh_from_db()
        self.assertEqual((Article.UNCLASSIFIED, None), (kept.status, kept.selection_criteria))
        self.assertFalse(kept.decisions.exists())
        self.assertEqual(ScreeningResult.PASSED, ScreeningResult.objects.get(run=run, article=kept).outcome)
        self.assertEqual([excluded.pk, kept.pk], [r.article_id for r in results])

    def test_threshold_is_inclusive_and_configurable(self):
        article = self.article()
        run = self.start(threshold=0.97)
        self.step(run, [EXCLUDE_E2])
        article.refresh_from_db()
        self.assertEqual(Article.REJECTED, article.status)

    def test_runs_in_steps(self):
        articles = [self.article() for _ in range(3)]
        run = self.start()
        with mock.patch.object(ai_screening, "STEP_SIZE", 2), mock.patch.object(jev, "evaluate", return_value=KEEP):
            first = ai_screening.process_step(run=run, actor=self.owner, size=2)
            run.refresh_from_db()
            self.assertEqual((2, ScreeningRun.RUNNING), (len(first), run.status))
            ai_screening.process_step(run=run, actor=self.owner, size=2)
            run.refresh_from_db()
        self.assertEqual(ScreeningRun.FINISHED, run.status)
        self.assertEqual(3, ai_screening.progress(run)["passed"])
        self.assertEqual([], ai_screening.process_step(run=run, actor=self.owner))  # finished runs do nothing
        self.assertEqual(3, len(articles))

    def test_errors_about_one_study_do_not_stop_the_run(self):
        no_text = self.article(title="", abstract="")
        too_long = self.article()
        fine = self.article()
        run = self.start()
        self.step(run, [jev.JevError("Jev answered 400: max_tokens_exceeded", status=400), EXCLUDE_E2])

        self.assertEqual(ScreeningRun.FINISHED, run.status)
        outcomes = dict(run.results.values_list("article_id", "outcome"))
        self.assertEqual(
            {no_text.pk: "error", too_long.pk: "error", fine.pk: "excluded"},
            outcomes,
        )
        self.assertIn("max_tokens_exceeded", run.results.get(article=too_long).error)
        too_long.refresh_from_db()
        self.assertEqual(Article.UNCLASSIFIED, too_long.status)

    def test_a_rejected_key_fails_the_run(self):
        self.article()
        self.article()
        run = self.start()
        error = jev.JevError("Jev rejected the API key. Update it in Settings → Integrations.", status=401, fatal=True)
        self.step(run, [error, error])
        self.assertEqual(ScreeningRun.FAILED, run.status)
        self.assertIn("rejected the API key", run.error)
        self.assertFalse(run.results.exists())
        self.assertEqual(0, Article.objects.filter(review=self.review, status=Article.REJECTED).count())

    def test_jev_unavailable_for_a_whole_step_fails_the_run(self):
        self.article()
        self.article()
        self.article()
        run = self.start()
        unavailable = jev.JevError("Jev answered 529: overloaded", status=529)
        with mock.patch.object(jev, "evaluate", side_effect=[unavailable, unavailable]):
            ai_screening.process_step(run=run, actor=self.owner, size=2)
        run.refresh_from_db()
        self.assertEqual((ScreeningRun.FAILED, "Jev answered 529: overloaded"), (run.status, run.error))
        self.assertEqual(
            {"failed": 2, "processed": 2}, {k: ai_screening.progress(run)[k] for k in ("failed", "processed")}
        )

    def test_a_study_classified_meanwhile_keeps_its_status(self):
        article = self.article()
        run = self.start()
        Article.objects.filter(pk=article.pk).update(status=Article.ACCEPTED)
        self.step(run, [EXCLUDE_E2])
        article.refresh_from_db()
        self.assertEqual(Article.ACCEPTED, article.status)
        self.assertEqual("R", article.decisions.get().status)  # Jev's own vote is still recorded

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

    def test_cancel(self):
        self.article()
        self.article()
        run = self.start()
        with mock.patch.object(jev, "evaluate", return_value=KEEP):
            ai_screening.process_step(run=run, actor=self.owner, size=1)
        ai_screening.cancel_run(run=run)
        self.assertEqual(ScreeningRun.CANCELLED, run.status)
        self.assertEqual((2, 1), (run.total, ai_screening.progress(run)["processed"]))
        self.assertEqual([], ai_screening.process_step(run=run, actor=self.owner))


class TestScope(AiScreeningTestCase):
    def test_later_runs_skip_what_jev_already_evaluated(self):
        passed = self.article()
        failed = self.article()
        excluded_then_restored = self.article()
        run = self.start()
        self.step(run, [KEEP, jev.JevError("Jev answered 400: bad", status=400), EXCLUDE_E2])
        Article.objects.filter(pk=excluded_then_restored.pk).update(status=Article.UNCLASSIFIED)
        fresh = self.article()

        self.assertEqual(
            [failed.pk, fresh.pk], list(ai_screening.eligible_articles(self.review).values_list("pk", flat=True))
        )
        everything = ai_screening.eligible_articles(self.review, rescreen=True)
        self.assertEqual(
            {passed.pk, failed.pk, excluded_then_restored.pk, fresh.pk}, set(everything.values_list("pk", flat=True))
        )
        self.assertEqual(
            {"": {"all": 4, "new": 2}, str(self.source.pk): {"all": 4, "new": 2}},
            ai_screening.scope_counts(self.review),
        )

    def test_deleting_the_jev_agent_deletes_its_runs_and_decisions(self):
        article = self.article()
        run = self.start()
        self.step(run, [EXCLUDE_E2])
        agent = ReviewAgent.objects.get(review=self.review, kind=ReviewAgent.JEV)
        deleted = agents.delete_agent(review=self.review, actor=self.owner, agent_id=agent.user_id)
        self.assertEqual(1, deleted["decisions"])
        self.assertFalse(ScreeningRun.objects.filter(pk=run.pk).exists())
        article.refresh_from_db()
        self.assertEqual((Article.REJECTED, None), (article.status, article.updated_by))
