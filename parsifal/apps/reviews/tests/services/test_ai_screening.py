import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from parsifal.apps.accounts.models import Integration
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core import jev
from parsifal.apps.core.exceptions import NotFound, PermissionDenied, UpstreamError, ValidationError
from parsifal.apps.reviews.models import Article, ScreeningResult, ScreeningRun, SelectionCriteria, StudyDecision
from parsifal.apps.reviews.services import agents, ai_screening, decisions, screening_requests
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
    return answer({"exclusion": probabilities})


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

    def test_the_default_request_of_the_review(self):
        options = ai_screening.exclusion_options(self.review)
        context = ai_screening.default_context(self.review)
        study = {"title": "T", "abstract": "A"}
        state, questions = ai_screening.build_request(
            "exclusion", screening_requests.default("exclusion"), options, context, "", study
        )
        self.assertEqual(study, state["study"])
        self.assertEqual(
            ["RQ1: Which tools exist?", "RQ2: How are they evaluated?"], state["review"]["research_questions"]
        )
        self.assertNotIn("comparison", state["review"])  # empty fields are left out
        self.assertEqual(["exclusion"], list(questions))
        self.assertEqual(
            {
                "E1": "Not a primary study",
                "E2": "Not in English",
                "none": "No exclusion criterion clearly applies to the study, or telling it needs the full text.",
            },
            questions["exclusion"]["criteria"],
        )
        self.assertNotIn("guidance", questions["exclusion"]["instructions"])

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
        response = answer({"exclusion": {"E1": 0.33, "E2": 0.32, "none": 0.35}})
        probabilities, p_exclude, best = ai_screening.combine(response, options)
        self.assertEqual({"E1": 0.33, "E2": 0.32, "none": 0.35}, probabilities)
        self.assertEqual((0.65, "E1"), (p_exclude, best))
        with self.subTest(msg="an option left out of the answer counts as 0"):
            probabilities, p_exclude, best = ai_screening.combine(
                answer({"exclusion": {"E2": 0.8, "none": 0.2}}), options
            )
            self.assertEqual(({"E1": 0.0, "E2": 0.8, "none": 0.2}, 0.8, "E2"), (probabilities, p_exclude, best))
        with self.assertRaisesMessage(jev.JevError, "did not answer the exclusion question"):
            ai_screening.combine({"answers": {}}, options)
        with self.assertRaisesMessage(jev.JevError, "not numbers"):
            ai_screening.combine({"answers": {"exclusion": {"probabilities": {"E1": "x"}}}}, options)


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

        with self.subTest(msg="what is left out is the last run's"):
            partial = self.start(context={"objective": "Only this changed", "population": None})
            self.assertEqual("Only this changed", partial.parameters["context"]["objective"])
            self.assertEqual("Software engineering researchers", partial.parameters["context"]["population"])
            self.assertEqual(
                (["A", "D"], self.source.pk), (partial.parameters["statuses"], partial.parameters["source_id"])
            )
            self.assertEqual("Be strict.", self.start(statuses=["A"], source_id=0).parameters["guidance"])
            defaults = self.start(defaults=True)
            self.assertEqual(
                ("", 0.9, ["R", "U"], None),
                tuple(defaults.parameters[k] for k in ("guidance", "threshold", "statuses", "source_id")),
            )
            self.assertEqual("Find studies about screening automation.", defaults.parameters["context"]["objective"])

        with self.subTest(msg="a new run closes a run left behind"):
            run.refresh_from_db()
            self.assertEqual(ScreeningRun.CANCELLED, run.status)
            self.assertFalse(run.results.exists())

        with self.subTest(msg="every status, from every source"):
            self.assertEqual(4, self.start(statuses=["U", "R", "A", "D"], source_id="").total)


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
        self.assertEqual(["exclusion"], list(call.kwargs["questions"]))
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
        with self.assertRaisesMessage(ValidationError, "between 1 and 64"):
            ai_screening.process_step(run=run, actor=self.owner, size=65)

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


# Exclusion with the review inside the question, the keywords in the state and "none" first.
EDITED = {
    "state": {"title": "{{study.title}}", "keywords": "{{study.keywords}}", "abstract": "{{study.abstract}}"},
    "question": {
        "type": "choice",
        "instructions": {"review": "{{review}}", "task": "Which exclusion criterion does the study meet?"},
        "criteria": {"none": "Nothing applies.", "{{key}}": "{{criterion}}"},
    },
}


class TestRequestTemplate(AiScreeningTestCase):
    def test_a_run_keeps_its_template_and_the_next_run_starts_from_it(self):
        self.article()

        def template(phase):
            return ai_screening.starting_settings(self.review, phase)["template"]

        self.assertEqual(screening_requests.default("exclusion"), template("exclusion"))
        run = self.start(template=json.dumps(EDITED))
        self.assertEqual(EDITED, run.parameters["template"])
        self.assertEqual(EDITED, template("exclusion"))
        self.assertEqual(screening_requests.default("inclusion"), template("inclusion"))
        self.assertEqual(EDITED, self.start().parameters["template"])  # left out: the last run's
        self.assertEqual(screening_requests.default("exclusion"), self.start(template="").parameters["template"])
        runs = ScreeningRun.objects.count()
        with self.assertRaisesMessage(ValidationError, "not valid JSON"):
            self.start(template="{")
        self.assertEqual(runs, ScreeningRun.objects.count())

    def test_each_study_is_sent_as_the_template_says(self):
        self.article(title="A tool", keywords="screening", abstract="We built it.")
        run = self.start(template=EDITED)
        _results, evaluate = self.step(run, [KEEP])
        sent = evaluate.call_args.kwargs
        self.assertEqual({"title": "A tool", "keywords": "screening", "abstract": "We built it."}, sent["state"])
        question = sent["questions"]["exclusion"]
        self.assertEqual(["exclusion"], list(sent["questions"]))
        self.assertEqual("Find studies about screening automation.", question["instructions"]["review"]["objective"])
        self.assertEqual(
            {"none": "Nothing applies.", "E1": "Not a primary study", "E2": "Not in English"}, question["criteria"]
        )
        self.assertEqual("passed", run.results.get().outcome)

    def test_a_run_from_before_templates_uses_the_default(self):
        self.article(title="A tool")
        run = self.start()
        del run.parameters["template"]
        run.save(update_fields=["parameters"])
        _results, evaluate = self.step(run, [KEEP])
        default = screening_requests.default("exclusion")
        sent = evaluate.call_args.kwargs
        self.assertEqual({"title": "A tool", "abstract": "An abstract."}, sent["state"]["study"])
        self.assertEqual(
            default["question"]["instructions"]["task"], sent["questions"]["exclusion"]["instructions"]["task"]
        )

    def test_preview_sends_nothing(self):
        nothing = self.article(title="", abstract="")
        first = self.article(title="First", keywords="k")
        self.article(title="Second")
        accepted = self.article(title="Accepted", status=Article.ACCEPTED)
        with mock.patch.object(jev, "evaluate") as evaluate:
            preview = ai_screening.preview(review=self.review, actor=self.owner)
            evaluate.assert_not_called()
        self.assertEqual(first, preview["article"])  # the first one in scope with something to read
        self.assertEqual("jev-1.13.0", preview["request"]["model"])
        self.assertEqual({"title": "First", "abstract": "An abstract."}, preview["request"]["state"]["study"])
        self.assertEqual(["exclusion"], list(preview["request"]["questions"]))

        with self.subTest(msg="the settings of the window"):
            preview = ai_screening.preview(
                review=self.review,
                actor=self.owner,
                template=EDITED,
                model="jev-1.14.0",
                context={"objective": "Edited"},
                statuses=["A"],
            )
            self.assertEqual(accepted, preview["article"])
            review = preview["request"]["questions"]["exclusion"]["instructions"]["review"]
            self.assertEqual(("jev-1.14.0", "Edited"), (preview["request"]["model"], review["objective"]))

        with self.subTest(msg="one study"):
            preview = ai_screening.preview(
                review=self.review, actor=self.owner, article_id=accepted.pk, phase="inclusion"
            )
            self.assertEqual(["inclusion_I1"], list(preview["request"]["questions"]))
            with self.assertRaisesMessage(ValidationError, "no title or abstract"):
                ai_screening.preview(review=self.review, actor=self.owner, article_id=nothing.pk)
            with self.assertRaises(NotFound):
                ai_screening.preview(review=self.review, actor=self.owner, article_id=ArticleFactory().pk)

        with self.subTest(msg="without a Jev key: the default model"):
            preview = ai_screening.preview(review=self.review, actor=self.bot)
            self.assertEqual(jev.DEFAULT_MODEL, preview["request"]["model"])

        with self.assertRaisesMessage(ValidationError, "no studies with a title or abstract"):
            ai_screening.preview(review=self.review, actor=self.owner, statuses=["D"])
        with self.assertRaisesMessage(ValidationError, "must send the study"):
            ai_screening.preview(review=self.review, actor=self.owner, template={**EDITED, "state": {}})
        self.assertFalse(ScreeningRun.objects.exists())


def yes_no(probabilities_by_question, model="jev-1.13.0"):
    return {
        "model": model,
        "answers": {question_id: {"type": "noul", "noul": p} for question_id, p in probabilities_by_question.items()},
    }


def inclusion_answer(by_criterion, model="jev-1.13.0"):
    """The probability of yes (the study meets it) of each criterion's question: {"I1": p, …}."""
    return yes_no({f"inclusion_{key}": p for key, p in by_criterion.items()}, model=model)


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

    def test_one_yes_no_question_per_criterion(self):
        options = ai_screening.inclusion_options(self.review)
        self.assertEqual(
            [
                {"key": "I1", "id": self.about.pk, "description": "About screening"},
                {"key": "I2", "id": self.tool.pk, "description": "Implemented tool"},
            ],
            options,
        )
        state, questions = ai_screening.build_request(
            "inclusion",
            screening_requests.default("inclusion"),
            options,
            ai_screening.default_context(self.review),
            "Be strict.",
            {"title": "T"},
        )
        self.assertEqual(["inclusion_I1", "inclusion_I2"], list(questions))
        body = questions["inclusion_I2"]["instructions"]
        self.assertEqual(("Implemented tool", "Be strict."), (body["criterion"], body["guidance"]))
        self.assertEqual("Find studies about screening automation.", state["review"]["objective"])

    def test_combine_reads_each_criterions_answer(self):
        options = ai_screening.inclusion_options(self.review)
        response = yes_no({"inclusion_I1": 1.0, "inclusion_I2": 0.8})
        self.assertEqual({"I1": 1.0, "I2": 0.8}, ai_screening.combine_inclusion(response, options))
        with self.assertRaisesMessage(jev.JevError, "did not answer the question about I2"):
            ai_screening.combine_inclusion(yes_no({"inclusion_I1": 1.0}), options)
        with self.assertRaisesMessage(jev.JevError, "not numbers"):
            ai_screening.combine_inclusion(yes_no({"inclusion_I1": "yes", "inclusion_I2": 1.0}), options)

    def test_every_criterion_must_reach_its_own_threshold(self):
        thresholds = {"I1": 0.9, "I2": 0.85}
        self.assertEqual((True, "I2"), ai_screening.decide_inclusion({"I1": 0.95, "I2": 0.86}, thresholds))
        self.assertEqual(
            (True, "I2"), ai_screening.decide_inclusion({"I1": 0.95, "I2": 0.85}, thresholds)
        )  # inclusive
        self.assertEqual((False, "I2"), ai_screening.decide_inclusion({"I1": 0.99, "I2": 0.84}, thresholds))
        self.assertEqual((False, "I1"), ai_screening.decide_inclusion({"I1": 0.5, "I2": 0.6}, thresholds))

    def test_thresholds_per_criterion(self):
        self.article()
        run = self.start()
        self.assertEqual({"I1": 0.9, "I2": 0.9}, run.parameters["thresholds"])
        self.assertEqual(["A", "U"], run.parameters["statuses"])
        self.assertNotIn("threshold", run.parameters)
        self.assertEqual(
            {"I1": 0.95, "I2": 0.8}, self.start(thresholds={"I1": 0.95, "i2": "0.8"}).parameters["thresholds"]
        )
        with self.subTest(msg="left out: the last inclusion run's, matched by criterion"):
            self.assertEqual(
                {"I1": 0.95, "I2": 0.8}, ai_screening.starting_settings(self.review, "inclusion")["thresholds"]
            )
            self.assertEqual({"I1": 0.97, "I2": 0.8}, self.start(thresholds=["I1=0.97"]).parameters["thresholds"])
        with self.subTest(msg="threshold sets the ones left out"):
            self.assertEqual({"I1": 0.85, "I2": 0.85}, self.start(threshold=0.85).parameters["thresholds"])
            self.assertEqual(
                {"I1": 0.85, "I2": 0.6}, self.start(threshold=0.85, thresholds="I2=0.6").parameters["thresholds"]
            )
        with self.subTest(msg="a run from before took one threshold for every criterion"):
            last = self.review.screening_runs.filter(phase="inclusion").first()
            last.parameters = {**last.parameters, "threshold": 0.7}
            del last.parameters["thresholds"]
            last.save(update_fields=["parameters"])
            self.assertEqual(
                {"I1": 0.7, "I2": 0.7}, ai_screening.starting_settings(self.review, "inclusion")["thresholds"]
            )

        with self.subTest(msg="inclusion never rejects: a criterion may accept on a weaker yes, down to 0.01"):
            self.assertEqual(
                {"I1": 0.3, "I2": 0.01}, self.start(thresholds="I1=0.3,I2=0.01".split(",")).parameters["thresholds"]
            )
            self.assertEqual({"I1": 0.2, "I2": 0.2}, self.start(threshold=0.2).parameters["thresholds"])
        for kwargs, message in (
            ({"thresholds": {"I3": 0.9}}, "Unknown inclusion criterion I3: the run sends I1, I2."),
            ({"thresholds": {"I1": 0.005}}, "The threshold of I1 must be between 0.01 and 0.99."),
            ({"thresholds": {"I1": 1}}, "The threshold of I1 must be between 0.01 and 0.99."),
            ({"thresholds": {"I1": "high"}}, "The threshold of I1 must be a number."),
            ({"thresholds": ["I1"]}, "Write each threshold as KEY=value"),
            ({"threshold": 0.005}, "The threshold must be between 0.01 and 0.99."),
            ({"threshold": ""}, "The threshold must be a number."),
        ):
            with self.subTest(**kwargs), self.assertRaisesMessage(ValidationError, message):
                self.start(**kwargs)
        with self.assertRaisesMessage(ValidationError, "Per-criterion thresholds are for the inclusion criteria"):
            super().start(thresholds={"E1": 0.9})

    def test_each_criterion_is_compared_with_its_threshold(self):
        article = self.article()
        answer = inclusion_answer({"I1": 0.8, "I2": 0.95})
        self.step(self.start(thresholds={"I1": 0.75, "I2": 0.9}), [answer])
        article.refresh_from_db()
        self.assertEqual(Article.ACCEPTED, article.status)
        run = self.start(thresholds={"I1": 0.85, "I2": 0.9})
        self.step(run, [answer])
        result = run.results.get()
        self.assertEqual(("undecided", 0.8), (result.outcome, result.p_include))
        self.assertIn(
            "undecided, I1 0.80 below its threshold 0.85 — meets: I1 0.80, I2 0.95.", self.decision(article).comments
        )

    def test_a_run_from_before_uses_its_single_threshold(self):
        self.article()
        run = self.start()
        run.parameters = {**run.parameters, "threshold": 0.96}
        del run.parameters["thresholds"]
        run.save(update_fields=["parameters"])
        self.step(run, [BOTH_MET])  # I1 0.95
        self.assertEqual("undecided", run.results.get().outcome)

    def test_accepts_when_every_criterion_is_met_and_never_rejects(self):
        accepted = self.article(title="Accepted")
        not_met = self.article(title="I1 not met")
        unsure = self.article(title="I2 unsure")
        self.article(title="Out already", status=Article.REJECTED, updated_by=self.owner)
        run = self.start()
        self.assertEqual(("inclusion", 3), (run.phase, run.total))  # unclassified and accepted, by default

        self.step(run, [BOTH_MET, I1_NOT_MET, I2_UNSURE])

        progress = ai_screening.progress(run)
        self.assertEqual(
            ("finished", 1, 0, 2, 0),
            tuple(progress[k] for k in ("status", "included", "excluded", "undecided", "passed")),
        )
        for article, status, decision_status, comment in (
            (accepted, Article.ACCEPTED, "A", "meets every inclusion criterion — meets: I1 0.95, I2 0.97."),
            (
                not_met,
                Article.UNCLASSIFIED,
                "U",
                "undecided, I1 0.06 below its threshold 0.90 — meets: I1 0.06, I2 0.90.",
            ),
            (
                unsure,
                Article.UNCLASSIFIED,
                "U",
                "undecided, I2 0.40 below its threshold 0.90 — meets: I1 0.96, I2 0.40.",
            ),
        ):
            with self.subTest(article=article.title):
                article.refresh_from_db()
                self.assertEqual((status, None), (article.status, article.selection_criteria))
                decision = self.decision(article)
                self.assertEqual((decision_status, None), (decision.status, decision.selection_criteria))
                self.assertEqual(f"Include with AI (run {run.pk}, jev-1.13.0): {comment}", decision.comments)
        result = run.results.get(article=not_met)
        self.assertEqual(
            (ScreeningResult.UNDECIDED, 0.06, None, None, {"I1": 0.06, "I2": 0.9}),
            (result.outcome, result.p_include, result.p_exclude, result.selection_criteria_id, result.probabilities),
        )

    def test_the_threshold_is_inclusive_and_configurable(self):
        articles = [self.article(title=title) for title in ("0.93", "0.05", "0.95", "0.5")]
        answers = [inclusion_answer({"I1": p, "I2": 0.99}) for p in (0.93, 0.05, 0.95, 0.5)]
        strict = self.start(threshold=0.95)
        self.step(strict, answers)
        self.assertEqual(
            ["undecided", "undecided", "included", "undecided"],
            [strict.results.get(article=article).outcome for article in articles],
        )
        lenient = self.start(threshold=0.9)
        self.step(lenient, answers)
        self.assertEqual(
            ["included", "undecided", "included", "undecided"],
            [lenient.results.get(article=article).outcome for article in articles],
        )
        self.assertFalse(self.review.article_set.filter(status=Article.REJECTED).exists())

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
        self.step(super().start(), [KEEP, EXCLUDE_E1])  # phase 1 by the same reviewer: R and U only
        self.step(self.start(statuses=["U"]), [BOTH_MET])
        own.refresh_from_db()
        rejected.refresh_from_db()
        self.assertEqual((Article.ACCEPTED, Article.REJECTED), (own.status, rejected.status))

        run = self.start(statuses=["U", "R", "A", "D"])
        self.assertEqual(4, run.total)
        self.step(run, [I2_UNSURE, I1_NOT_MET, BOTH_MET, BOTH_MET])
        for article, status, decision_status in (
            (own, Article.UNCLASSIFIED, "U"),  # its own acceptance, undecided now: back to unclassified
            (theirs, Article.ACCEPTED, "U"),  # someone else's: kept, the reviewer's decision recorded
            (rejected, Article.REJECTED, "A"),  # even its own rejection: Include with AI never changes one
            (duplicated, Article.DUPLICATED, "A"),
        ):
            with self.subTest(article=article.title):
                article.refresh_from_db()
                self.assertEqual(status, article.status)
                self.assertEqual(decision_status, self.decision(article).status)

    def test_requirements(self):
        self.article()
        with self.assertRaisesMessage(ValidationError, "phase must be exclusion, inclusion or screen"):
            self.start(phase="maybe")
        with self.assertRaisesMessage(ValidationError, "Retain with AI was removed"):
            self.start(phase="retention")
        no_inclusion = ReviewFactory(author=self.owner, sources=[self.source])
        SelectionCriteria.objects.create(review=no_inclusion, criteria_type="E", description="Out")
        ArticleFactory(review=no_inclusion, source=self.source)
        with self.assertRaisesMessage(ValidationError, "no inclusion criteria"):
            self.start(review=no_inclusion, reviewer_id=self.owner.pk)
        self.assertEqual(["A", "U"], ai_screening.clean_statuses(None, "inclusion"))


class TestInclusionRule(AiScreeningTestCase):
    """The protocol's rule "any": one inclusion criterion met is enough."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        SelectionCriteria.objects.create(review=cls.review, criteria_type="I", description="Implemented tool")

    def start(self, **kwargs):
        return super().start(**{"phase": "inclusion", **kwargs})

    def test_one_criterion_is_enough(self):
        thresholds = {"I1": 0.9, "I2": 0.85}
        self.assertEqual((True, "I1"), ai_screening.decide_inclusion({"I1": 0.95, "I2": 0.1}, thresholds, "any"))
        self.assertEqual((True, "I2"), ai_screening.decide_inclusion({"I1": 0.91, "I2": 0.99}, thresholds, "any"))
        self.assertEqual((False, "I2"), ai_screening.decide_inclusion({"I1": 0.5, "I2": 0.84}, thresholds, "any"))
        self.assertEqual((False, "I2"), ai_screening.decide_inclusion({"I1": 0.95, "I2": 0.1}, thresholds, "all"))

    def test_runs_follow_the_protocols_rule_and_keep_it(self):
        one, none = self.article(title="One"), self.article(title="None")
        self.review.inclusion_rule = "any"
        self.review.save()
        run = self.start()
        self.assertEqual("any", run.parameters["inclusion_rule"])
        self.step(run, [I1_NOT_MET, inclusion_answer({"I1": 0.2, "I2": 0.3})])  # I2 0.90 reaches its threshold
        self.assertEqual(["included", "undecided"], [run.results.get(article=a).outcome for a in (one, none)])
        self.assertIn(
            "meets I2, and one inclusion criterion is enough — meets: I1 0.06, I2 0.90.", self.decision(one).comments
        )
        self.assertIn(
            "undecided, no inclusion criterion reaches its threshold (closest: I2 0.30 for 0.90)",
            self.decision(none).comments,
        )
        self.assertEqual(0.9, run.results.get(article=one).p_include)
        # A run made before the rule (all of them) is honoured as it was.
        self.review.inclusion_rule = "all"
        self.review.save()
        self.assertEqual("any", ScreeningRun.objects.get(pk=run.pk).parameters["inclusion_rule"])


class TestCriteriaChoice(AiScreeningTestCase):
    def test_only_the_criteria_chosen_are_sent_and_the_next_run_keeps_the_choice(self):
        self.article()
        run = self.start(criteria_ids=[self.english.pk])
        self.assertEqual(["E2"], [option["key"] for option in run.parameters["criteria"]])  # its key in the protocol
        self.assertEqual([self.secondary.pk], run.parameters["skipped_criteria"])
        _results, evaluate = self.step(run, [same_answer({"E2": 0.95, "none": 0.05})])
        self.assertEqual({"E2", "none"}, set(evaluate.call_args.kwargs["questions"]["exclusion"]["criteria"]))
        self.assertEqual("excluded", run.results.get().outcome)
        # The next run leaves out what this one left out; a criterion added since is sent.
        added = SelectionCriteria.objects.create(review=self.review, criteria_type="E", description="Old year")
        self.assertEqual(
            [self.english.pk, added.pk], ai_screening.starting_settings(self.review, "exclusion")["criteria_ids"]
        )
        self.assertEqual({"E2", "E3"}, {option["key"] for option in self.start().parameters["criteria"]})
        self.assertEqual(3, len(self.start(defaults=True).parameters["criteria"]))

    def test_what_cannot_be_chosen(self):
        self.article()
        inclusion = self.review.selectioncriteria_set.get(criteria_type="I")
        for criteria_ids, message in (
            ([], "Choose at least one exclusion criterion"),
            ([inclusion.pk], "is not one of the review's exclusion criteria"),
            (["x"], "Criteria are given by their ids"),
        ):
            with self.subTest(criteria_ids=criteria_ids), self.assertRaisesMessage(ValidationError, message):
                self.start(criteria_ids=criteria_ids)
        with self.assertRaisesMessage(ValidationError, "Choose at least one inclusion criterion"):
            self.start(phase="screen", criteria_ids=[self.secondary.pk])


class TestStartingSettings(AiScreeningTestCase):
    def test_the_last_run_of_the_same_action_or_the_defaults(self):
        self.article()
        settings = ai_screening.starting_settings(self.review, "exclusion")
        self.assertIsNone(settings["run"])
        self.assertEqual(
            (None, 0.9, ["R", "U"], None, ""),
            tuple(settings[k] for k in ("model", "threshold", "statuses", "source_id", "guidance")),
        )
        run = self.start(threshold=0.8, guidance="Strict.", statuses=["U"], context={"objective": "Edited"})
        self.start(phase="inclusion")
        settings = ai_screening.starting_settings(self.review, "exclusion")
        self.assertEqual(
            (run, self.bot.pk, "jev-1.13.0", 0.8, ["U"], "Strict.", "Edited"),
            (
                settings["run"],
                settings["reviewer_id"],
                settings["model"],
                settings["threshold"],
                settings["statuses"],
                settings["guidance"],
                settings["context"]["objective"],
            ),
        )
        restored = ai_screening.starting_settings(self.review, "exclusion", defaults=True)
        self.assertEqual((None, 0.9, ""), (restored["run"], restored["threshold"], restored["guidance"]))
        self.assertEqual(screening_requests.default("exclusion"), restored["template"])


class TestScreen(AiScreeningTestCase):
    """Screen with AI: the exclusion question and the inclusion questions in one request."""

    def start(self, **kwargs):
        return super().start(**{"phase": "screen", **kwargs})

    def response(self, exclusion, inclusion):
        return {
            "model": "jev-1.13.0",
            "answers": {
                "exclusion": {"type": "choice", "probabilities": exclusion},
                **{f"inclusion_{key}": {"type": "noul", "noul": p} for key, p in inclusion.items()},
            },
        }

    def test_one_request_with_both_questions(self):
        options = ai_screening.criteria_options(self.review, "screen")
        self.assertEqual(["E1", "E2", "I1"], [option["key"] for option in options])
        _state, questions = ai_screening.build_request(
            "screen",
            screening_requests.default("screen"),
            options,
            ai_screening.default_context(self.review),
            "",
            {"title": "T"},
        )
        self.assertEqual(["exclusion", "inclusion_I1"], list(questions))
        self.assertEqual({"E1", "E2", "none"}, set(questions["exclusion"]["criteria"]))
        self.article()
        run = self.start()
        self.assertEqual(
            ("screen", 0.9, {"I1": 0.9}, "all", ["A", "R", "U"]),
            tuple(
                run.parameters.get(k, run.phase)
                for k in ("phase", "threshold", "thresholds", "inclusion_rule", "statuses")
            ),
        )

    def test_the_exclusion_threshold_starts_at_half_the_inclusion_ones_lower(self):
        self.article()
        run = self.start(threshold=0.5, thresholds={"I1": 0.2})
        self.assertEqual((0.5, {"I1": 0.2}), (run.parameters["threshold"], run.parameters["thresholds"]))
        with self.assertRaisesMessage(ValidationError, "The threshold must be between 0.5 and 0.99."):
            self.start(threshold=0.2)

    def test_exclusion_wins_then_inclusion_accepts_else_undecided(self):
        both = self.article(title="Excluded and included")
        included = self.article(title="Included")
        undecided = self.article(title="Undecided")
        own = self.article(title="Accepted by this reviewer", status=Article.ACCEPTED, updated_by=self.bot)
        run = self.start()
        _results, evaluate = self.step(
            run,
            [
                self.response({"E1": 0.95, "E2": 0.0, "none": 0.05}, {"I1": 0.99}),
                self.response({"E1": 0.05, "E2": 0.05, "none": 0.9}, {"I1": 0.95}),
                self.response({"E1": 0.05, "E2": 0.05, "none": 0.9}, {"I1": 0.4}),
                self.response({"E1": 0.05, "E2": 0.05, "none": 0.9}, {"I1": 0.4}),
            ],
        )
        self.assertEqual(4, evaluate.call_count)  # one request per study
        for article, outcome, status, criterion in (
            (both, "excluded", Article.REJECTED, self.secondary),
            (included, "included", Article.ACCEPTED, None),
            (undecided, "undecided", Article.UNCLASSIFIED, None),
            (own, "undecided", Article.UNCLASSIFIED, None),  # its own acceptance, undecided now
        ):
            with self.subTest(article=article.title):
                article.refresh_from_db()
                self.assertEqual(outcome, run.results.get(article=article).outcome)
                self.assertEqual((status, criterion), (article.status, article.selection_criteria))
        self.assertIn(
            "E1, p(exclude) = 0.95 (inclusion: meets every inclusion criterion", self.decision(both).comments
        )
        self.assertTrue(
            self.decision(included).comments.startswith(f"Screen with AI (run {run.pk}, jev-1.13.0): meets")
        )
        result = run.results.get(article=both)
        self.assertEqual((0.95, 0.99), (result.p_exclude, result.p_include))
        self.assertEqual({"E1": 0.95, "E2": 0.0, "none": 0.05, "I1": 0.99}, result.probabilities)
        progress = ai_screening.progress(run)
        self.assertEqual((1, 1, 2), (progress["excluded"], progress["included"], progress["undecided"]))

    def test_needs_criteria_of_both_kinds(self):
        bare = ReviewFactory(author=self.owner, sources=[self.source])
        ArticleFactory(review=bare, source=self.source)
        SelectionCriteria.objects.create(review=bare, criteria_type="E", description="Out")
        with self.assertRaisesMessage(
            ValidationError, "The review has no inclusion criteria. Screen with AI asks about both."
        ):
            self.start(review=bare, reviewer_id=self.owner.pk)


class TestRelevance(AiScreeningTestCase):
    """How likely a study is relevant, by the latest AI answer: shown in the study list and sortable."""

    def test_by_action(self):
        self.assertEqual(0.9, ai_screening.relevance("exclusion", 0.1, None))
        self.assertEqual(0.8, ai_screening.relevance("inclusion", None, 0.8))
        self.assertEqual(0.3, ai_screening.relevance("screen", 0.7, 0.95))
        self.assertEqual(0.6, ai_screening.relevance("retention", None, 0.6))
        self.assertIsNone(ai_screening.relevance("exclusion", None, None))

    def test_the_latest_answer_ranks_the_studies(self):
        unlikely, likely, unscreened = self.article(title="B"), self.article(title="A"), self.article(title="C")
        run = self.start(statuses=["U"])
        self.step(run, [EXCLUDE_E2, KEEP, KEEP])
        ScreeningResult.objects.filter(run=run, article=unscreened).update(outcome=ScreeningResult.ERROR)
        from parsifal.apps.reviews.services import studies

        ranked = list(studies.list_articles(self.review, order="ai_score"))
        self.assertEqual([likely, unlikely, unscreened], ranked)  # 0.90, 0.03, none
        self.assertEqual([0.9, 0.03, None], [article.ai_score for article in ranked])
        self.assertEqual(0.03, Article.objects.get(pk=unlikely.pk).ai_score)  # looked up when not annotated
        self.assertEqual([likely, unlikely, unscreened], list(studies.list_articles(self.review)))  # by title
        self.assertEqual([unlikely, likely, unscreened], list(studies.list_articles(self.review, order="-ai_score")))
        with self.assertRaisesMessage(ValidationError, "order must be one of title, ai_score"):
            studies.list_articles(self.review, order="nope")


class TestResultStatus(AiScreeningTestCase):
    """What a result shows: only the statuses the study list has (never "passed" or "undecided")."""

    def test_the_status_the_run_gave_and_the_one_kept(self):
        for title in ("Rejected", "Passed"):
            self.article(title=title)
        self.article(title="Accepted by the owner", status=Article.ACCEPTED, updated_by=self.owner)
        run = self.start(statuses=["U", "A"])
        self.step(run, [EXCLUDE_E2, KEEP, EXCLUDE_E1])
        statuses = {
            result.article.title: (ai_screening.result_status(result), ai_screening.kept_status(result))
            for result in run.results.select_related("article", "run")
        }
        self.assertEqual(
            {
                "Rejected": (Article.REJECTED, None),
                "Passed": (Article.UNCLASSIFIED, None),
                "Accepted by the owner": (Article.REJECTED, Article.ACCEPTED),  # the reviewer's decision; kept
            },
            statuses,
        )
        self.assertEqual({"R", "U", "A"}, set(ai_screening.STATUS_NAMES) - {"D"})
