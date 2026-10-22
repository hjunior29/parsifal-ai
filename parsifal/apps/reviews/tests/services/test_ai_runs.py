from datetime import timedelta
from unittest import mock

from django.utils import timezone

from parsifal.apps.accounts.models import Integration
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core import jev
from parsifal.apps.core.exceptions import Conflict, PermissionDenied, ValidationError
from parsifal.apps.reviews.models import Article, ScreeningResult, ScreeningRun, SelectionCriteria, StudyDecision
from parsifal.apps.reviews.services import ai_runs, ai_screening, decisions, screening_requests
from parsifal.apps.reviews.tests.services.test_ai_screening import EXCLUDE_E2, KEEP, AiScreeningTestCase


class AiRunsTestCase(AiScreeningTestCase):
    def setUp(self):
        # Who last edited the studies before any run, and when.
        self.editor = UserFactory()
        self.earlier = (timezone.now() - timedelta(days=2)).replace(microsecond=0)

    def article(self, **kwargs):
        article = super().article(**kwargs)
        Article.objects.filter(pk=article.pk).update(updated_by=self.editor, updated_at=self.earlier)
        return article

    def screen(self, responses, **kwargs):
        run = self.start(**kwargs)
        self.step(run, responses)
        return run

    def state(self, article):
        article.refresh_from_db()
        return article.status, article.selection_criteria_id, article.updated_by_id, article.updated_at

    def original(self):
        return Article.UNCLASSIFIED, None, self.editor.pk, self.earlier

    def preview(self, run, actor=None):
        return ai_runs.undo_preview(review=self.review, actor=actor or self.owner, run_id=run.pk)

    def undo(self, run, actor=None):
        return ai_runs.undo_run(review=self.review, actor=actor or self.owner, run_id=run.pk)

    def counts(self, summary):
        names = ("screened", "statuses_restored", "statuses_kept", "decisions_restored", "decisions_removed")
        names += ("decisions_kept",)
        return {name: summary[name] for name in names}


class TestWhatARunKeeps(AiRunsTestCase):
    def test_the_study_and_decision_from_before(self):
        rejected, passed = self.article(), self.article()
        run = self.screen([EXCLUDE_E2, KEEP])
        result = run.results.get(article=rejected)
        self.assertEqual(("R", "U", None), (result.status_set, result.previous_status, result.previous_criteria_id))
        self.assertEqual((self.editor.pk, self.earlier), (result.previous_updated_by_id, result.previous_updated_at))
        self.assertIsNone(result.previous_decision)
        # The study's last change is the run's: undoing it can tell whether anyone changed the study since.
        self.assertEqual(("R", self.english.pk, self.bot.pk, result.processed_at), self.state(rejected))
        self.assertEqual(run, self.decision(rejected).run)
        # A study the run did not change keeps nothing of it.
        result = run.results.get(article=passed)
        self.assertEqual(("", None), (result.status_set, result.previous_updated_by_id))
        self.assertEqual(self.original(), self.state(passed))
        self.assertEqual(run, self.decision(passed).run)

    def test_a_later_run_keeps_the_decision_it_replaced(self):
        article = self.article()
        first = self.screen([EXCLUDE_E2])
        decision = self.decision(article)
        second = self.screen([KEEP])
        self.assertEqual(
            {
                "status": "R",
                "criteria_id": self.english.pk,
                "comments": decision.comments,
                "decided_at": decision.decided_at.isoformat(),
                "run_id": first.pk,
            },
            second.results.get().previous_decision,
        )
        result = second.results.get()
        self.assertEqual(
            ("U", "R", self.bot.pk), (result.status_set, result.previous_status, result.previous_updated_by_id)
        )

    def test_a_decision_made_by_hand_belongs_to_no_run(self):
        article = self.article()
        self.screen([EXCLUDE_E2])
        decisions.record_decision(review=self.review, article_id=article.pk, actor=self.bot, status="A")
        self.assertIsNone(self.decision(article).run)


class TestUndo(AiRunsTestCase):
    def test_studies_go_back_and_new_decisions_are_removed(self):
        rejected, passed = self.article(), self.article()
        run = self.screen([EXCLUDE_E2, KEEP])
        summary = self.preview(run)
        self.assertEqual(
            {
                "screened": 2,
                "statuses_restored": 1,
                "statuses_kept": 0,
                "decisions_restored": 0,
                "decisions_removed": 2,
                "decisions_kept": 0,
            },
            self.counts(summary),
        )
        self.assertEqual({"U": 1}, summary["back_to"])
        self.assertEqual(
            f"Undoing run {run.pk}: 1 study goes back to the status from before the run (1 unclassified); 2 decisions "
            f"of {self.bot.username} are removed (there was none before). The run and its answers are deleted.",
            summary["message"],
        )
        self.assertEqual(self.counts(summary), self.counts(self.undo(run)))
        self.assertEqual(self.original(), self.state(rejected))
        self.assertEqual(self.original(), self.state(passed))
        self.assertFalse(StudyDecision.objects.filter(user=self.bot).exists())
        self.assertFalse(ScreeningRun.objects.filter(pk=run.pk).exists())
        self.assertFalse(ScreeningResult.objects.filter(run_id=run.pk).exists())

    def test_the_decision_the_run_replaced_comes_back(self):
        article = self.article()
        decisions.record_decision(
            review=self.review, article_id=article.pk, actor=self.bot, status="A", comments="Read it."
        )
        StudyDecision.objects.filter(user=self.bot).update(decided_at=self.earlier)
        run = self.screen([EXCLUDE_E2])
        self.assertEqual(1, self.preview(run)["decisions_restored"])
        self.undo(run)
        decision = self.decision(article)
        self.assertEqual(
            ("A", None, "Read it.", self.earlier, None),
            (decision.status, decision.selection_criteria_id, decision.comments, decision.decided_at, decision.run_id),
        )
        self.assertEqual(self.original(), self.state(article))

    def test_what_changed_since_stays(self):
        by_hand, decided_again, both = self.article(), self.article(), self.article()
        run = self.screen([EXCLUDE_E2, EXCLUDE_E2, EXCLUDE_E2])
        now = timezone.now()
        Article.objects.filter(pk__in=[by_hand.pk, both.pk]).update(status="A", updated_by=self.owner, updated_at=now)
        for article in (decided_again, both):
            decisions.record_decision(review=self.review, article_id=article.pk, actor=self.bot, status="A")
        summary = self.undo(run)
        self.assertEqual(
            {
                "screened": 3,
                "statuses_restored": 1,
                "statuses_kept": 2,
                "decisions_restored": 0,
                "decisions_removed": 1,
                "decisions_kept": 2,
            },
            self.counts(summary),
        )
        self.assertIn(
            "2 studies whose status changed again since the run kept the newer status. "
            f"2 decisions of {self.bot.username} replaced since the run stayed.",
            summary["message"],
        )
        # Changed by hand: keeps its status; the run's decision on it is removed.
        status, _criteria, updated_by, _updated_at = self.state(by_hand)
        self.assertEqual(("A", self.owner.pk), (status, updated_by))
        self.assertFalse(StudyDecision.objects.filter(article=by_hand).exists())
        # Decided again by hand: the study goes back, the new decision stays.
        self.assertEqual(self.original(), self.state(decided_again))
        self.assertEqual(("A", None), (self.decision(decided_again).status, self.decision(decided_again).run))
        # Both: left as it is.
        self.assertEqual("A", self.state(both)[0])
        self.assertEqual("A", self.decision(both).status)

    def test_other_reviewers_are_not_touched(self):
        article = self.article()
        decisions.record_decision(review=self.review, article_id=article.pk, actor=self.other_bot, status="A")
        run = self.screen([EXCLUDE_E2])
        self.undo(run)
        self.assertEqual("A", self.decision(article, self.other_bot).status)

    def test_an_interrupted_run(self):
        screened, waiting = self.article(), self.article()
        run = self.start()
        with mock.patch.object(jev, "evaluate", side_effect=[EXCLUDE_E2]):
            ai_screening.process_step(run=run, actor=self.owner, size=1)
        ScreeningRun.objects.filter(pk=run.pk).update(last_step_at=None)  # its window was closed a while ago
        run.refresh_from_db()
        self.assertEqual(ScreeningRun.RUNNING, run.status)
        self.assertEqual(1, self.undo(run)["screened"])
        self.assertEqual(self.original(), self.state(screened))
        self.assertEqual(self.original(), self.state(waiting))
        self.assertFalse(ScreeningRun.objects.exists())

    def test_a_criterion_deleted_since(self):
        article = self.article()
        decisions.record_decision(
            review=self.review, article_id=article.pk, actor=self.bot, status="R", criteria_id=self.secondary.pk
        )
        run = self.screen([EXCLUDE_E2])
        self.secondary.delete()
        self.undo(run)
        self.assertEqual(("R", None), (self.decision(article).status, self.decision(article).selection_criteria_id))


class TestChainOfRuns(AiRunsTestCase):
    """A study screened by two runs of one reviewer: the first rejects it, the second passes it."""

    def two_runs(self):
        article = self.article()
        first = self.screen([EXCLUDE_E2])
        second = self.screen([KEEP])
        self.assertEqual(("U", None, self.bot.pk), self.state(article)[:3])
        return article, first, second

    def test_undone_from_the_newest(self):
        article, first, second = self.two_runs()
        self.undo(second)
        processed = first.results.get().processed_at
        self.assertEqual(("R", self.english.pk, self.bot.pk, processed), self.state(article))
        self.assertEqual(("R", first), (self.decision(article).status, self.decision(article).run))
        self.undo(first)
        self.assertEqual(self.original(), self.state(article))
        self.assertFalse(StudyDecision.objects.exists())

    def test_only_the_latest(self):
        article, first, second = self.two_runs()
        with self.assertRaisesMessage(
            ValidationError, f"Only the latest run can be undone: undo run {second.pk} first."
        ):
            self.preview(first)
        with self.assertRaisesMessage(ValidationError, "Only the latest run"):
            self.undo(first)
        self.assertEqual(("U", None, self.bot.pk), self.state(article)[:3])
        controls = ai_runs.controls(self.review, self.owner, [first, second])
        self.assertEqual((False, True), (controls[first.pk]["latest"], controls[second.pk]["latest"]))
        self.assertIn(f"undo run {second.pk} first", controls[first.pk]["undo_problem"])
        self.assertEqual("", controls[second.pk]["undo_problem"])

    def test_the_latest_whoever_its_reviewer(self):
        article, first, second = self.two_runs()
        other = self.screen([KEEP], reviewer_id=self.other_bot.pk)
        with self.assertRaisesMessage(ValidationError, f"undo run {other.pk} first"):
            self.undo(second)
        self.undo(other)
        self.assertFalse(StudyDecision.objects.filter(user=self.other_bot).exists())
        self.undo(second)
        self.undo(first)
        self.assertEqual(self.original(), self.state(article))
        self.assertFalse(StudyDecision.objects.exists())


class TestWhoAndWhen(AiRunsTestCase):
    def test_runs_from_before_cannot_be_undone(self):
        self.article()
        run = self.screen([EXCLUDE_E2])
        ScreeningRun.objects.filter(pk=run.pk).update(undoable=False)
        run.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "cannot be undone"):
            self.undo(run)
        control = ai_runs.controls(self.review, self.owner, [run])[run.pk]
        self.assertIsNone(control["standing"])
        self.assertIn("before Parsifal kept", control["undo_problem"])

    def test_the_main_author_or_the_runs_own_reviewer(self):
        coauthor = UserFactory()
        self.review.co_authors.add(coauthor)
        Integration.objects.create(user=coauthor, provider=Integration.JEV, api_key="fake-key", model="jev-1.13.0")
        self.article()
        run = self.screen([EXCLUDE_E2])
        with self.assertRaisesMessage(PermissionDenied, "Only the main author"):
            self.undo(run, actor=coauthor)
        self.assertIn("Only the main author", ai_runs.controls(self.review, coauthor, [run])[run.pk]["undo_problem"])
        own = self.screen([KEEP], actor=coauthor, reviewer_id=coauthor.pk)
        self.undo(own, actor=coauthor)
        self.assertFalse(ScreeningRun.objects.filter(pk=own.pk).exists())

    def test_not_while_a_run_is_being_screened(self):
        self.article()
        run = self.screen([EXCLUDE_E2])
        busy = self.start()
        ScreeningRun.objects.filter(pk=busy.pk).update(last_step_at=timezone.now())
        with self.assertRaisesMessage(Conflict, f"Run {busy.pk} is being screened right now"):
            self.undo(busy)
        ScreeningRun.objects.filter(pk=busy.pk).update(last_step_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(0, self.undo(busy)["screened"])  # interrupted before screening anything: only deleted
        self.undo(run)
        self.assertFalse(ScreeningRun.objects.exists())

    def test_standing_counts_the_decisions_still_the_runs(self):
        first = self.article()
        self.article()
        run = self.screen([EXCLUDE_E2, KEEP])
        self.assertEqual({run.pk: 2}, ai_runs.standing(self.review))
        decisions.record_decision(review=self.review, article_id=first.pk, actor=self.bot, status="A")
        control = ai_runs.controls(self.review, self.owner, [run])[run.pk]
        self.assertEqual({"standing": 1, "latest": True, "undo_problem": ""}, control)


class TestImpact(AiRunsTestCase):
    def impact(self, **kwargs):
        return ai_runs.impact(review=self.review, actor=self.owner, **{"reviewer_id": self.bot.pk, **kwargs})

    def test_nothing_to_rewrite(self):
        self.article()
        self.article()
        impact = self.impact()
        self.assertEqual(
            (2, 0, 0, False), (impact["studies"], impact["decisions"], impact["classified"], impact["confirm"])
        )
        self.assertEqual(
            f"This run sends 2 studies; {self.bot.username} has no decisions on them yet.", impact["message"]
        )

    def test_decisions_and_studies_the_reviewer_classified(self):
        self.article()
        self.article()
        run = self.screen([EXCLUDE_E2, KEEP])
        impact = self.impact()
        self.assertEqual(
            (2, 2, 1, True), (impact["studies"], impact["decisions"], impact["classified"], impact["confirm"])
        )
        self.assertEqual(
            f"This run sends 2 studies and rewrites 2 decisions of {self.bot.username} and may change the status of 1 "
            f"study {self.bot.username} rejected. While it is the latest run, it can be undone in AI runs.",
            impact["message"],
        )
        # Inclusion only changes the studies the reviewer accepted; another reviewer has nothing to rewrite.
        self.assertEqual(0, self.impact(phase="inclusion", statuses=["U", "R"])["classified"])
        self.assertFalse(self.impact(reviewer_id=self.other_bot.pk)["confirm"])
        # Doing a run again: its settings fill in the rest.
        self.assertEqual(impact, ai_runs.impact(review=self.review, actor=self.owner, run_id=run.pk))
        retention = ai_runs.impact(review=self.review, actor=self.owner, run_id=run.pk, statuses=["U", "R", "A"])
        self.assertIn("accepted or rejected", self.impact(phase="screen")["message"])
        self.assertEqual(2, retention["studies"])


class TestRunAgain(AiRunsTestCase):
    def test_the_same_settings(self):
        self.article(source=self.other_source)
        template = screening_requests.default("exclusion")
        template["question"]["instructions"]["task"] = "Screen carefully."
        run = self.screen(
            [EXCLUDE_E2],
            threshold=0.7,
            guidance="Tertiary studies count as secondary.",
            context={"objective": "Another objective."},
            template=template,
            source_id=self.other_source.pk,
            statuses=["U"],
        )
        settings = ai_runs.rerun_settings(self.review, run)
        self.assertEqual(
            {
                "phase": "exclusion",
                "reviewer_id": self.bot.pk,
                "model": "jev-1.13.0",
                "guidance": "Tertiary studies count as secondary.",
                "template": run.parameters["template"],
                "source_id": self.other_source.pk,
                "statuses": ["U"],
                "criteria_ids": [self.secondary.pk, self.english.pk],
                "threshold": 0.7,
                "thresholds": None,
            },
            {name: value for name, value in settings.items() if name != "context"},
        )
        self.assertEqual("Another objective.", settings["context"]["objective"])
        again = ai_runs.rerun(review=self.review, actor=self.owner, run_id=run.pk, statuses=["U", "R"])
        self.assertEqual(["R", "U"], again.parameters["statuses"])
        self.assertEqual({**run.parameters, "statuses": ["R", "U"]}, again.parameters)
        self.assertEqual((again.reviewer, again.model, again.phase), (run.reviewer, run.model, run.phase))

    def test_inclusion_thresholds_follow_their_criteria(self):
        self.article()
        about = self.review.selectioncriteria_set.get(criteria_type="I")
        tool = SelectionCriteria.objects.create(review=self.review, criteria_type="I", description="Implemented tool")
        run = self.start(phase="inclusion", thresholds={"I1": 0.8, "I2": 0.95})
        # A new criterion listed first moves the keys: each threshold stays with its criterion.
        SelectionCriteria.objects.create(review=self.review, criteria_type="I", description="Aa new criterion")
        settings = ai_runs.rerun_settings(self.review, run)
        self.assertEqual({"I1": 0.9, "I2": 0.8, "I3": 0.95}, settings["thresholds"])
        self.assertEqual([about.pk, tool.pk], [option["id"] for option in run.parameters["criteria"]])
        # One threshold given replaces them all.
        again = ai_runs.rerun(review=self.review, actor=self.owner, run_id=run.pk, threshold=0.6)
        self.assertEqual({"I1": 0.6, "I2": 0.6, "I3": 0.6}, again.parameters["thresholds"])
