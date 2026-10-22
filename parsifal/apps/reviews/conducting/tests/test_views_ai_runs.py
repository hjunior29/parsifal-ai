from datetime import timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from parsifal.apps.accounts.models import Integration
from parsifal.apps.core import jev
from parsifal.apps.reviews.conducting.tests.test_views_ai_screening import EXCLUDE, AiScreeningViewsBase
from parsifal.apps.reviews.models import Article, ScreeningRun, StudyDecision
from parsifal.apps.reviews.services import ai_screening, decisions


class AiRunsViewsTest(AiScreeningViewsBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.list_url = reverse("reviews:conducting:ai_runs")
        cls.run_url = reverse("reviews:conducting:ai_run")
        cls.undo_url = reverse("reviews:conducting:ai_run_undo")
        cls.impact_url = reverse("reviews:conducting:ai_screening_impact")

    def screen(self, **extra):
        if not Integration.objects.filter(user=self.owner).exists():
            self.connect()
        run = ScreeningRun.objects.get(pk=self.start(guidance="Be strict.", **extra).json()["run"]["id"])
        with mock.patch.object(jev, "evaluate", return_value=EXCLUDE):
            ai_screening.process_step(run=run, actor=self.owner)
        ScreeningRun.objects.filter(pk=run.pk).update(last_step_at=timezone.now() - timedelta(minutes=5))
        run.refresh_from_db()
        return run

    def test_button_next_to_reviewer_agreement(self):
        page = self.client.get(reverse("study_selection", args=(self.owner.username, self.review.name)))
        self.assertContains(page, 'id="btn-ai-runs"', html=False)
        self.assertContains(page, 'id="modal-ai-runs"', html=False)
        content = page.content.decode()
        self.assertLess(content.index('id="btn-ai-runs"'), content.index('id="btn-agreement"'))

    def test_the_list(self):
        response = self.client.get(self.list_url, {"review-id": self.review.pk})
        self.assertContains(response, "No AI runs yet.")
        older = self.screen()
        run = self.screen()
        response = self.client.get(self.list_url, {"review-id": self.review.pk})
        self.assertContains(response, "Exclude with AI")
        self.assertContains(response, self.bot.username)
        self.assertContains(response, "Threshold 0.90")
        self.assertContains(response, "Rejected, Unclassified")
        self.assertContains(response, "1 rejected · 0 unclassified")
        # Undo on the latest run only.
        self.assertContains(response, f'data-run-id="{run.pk}">Undo</button>', html=False)
        self.assertNotContains(response, f'data-run-id="{older.pk}">Undo</button>', html=False)
        self.assertNotContains(response, "cannot be undone")
        # The newer run replaced the older one's decision: nothing of the older one stands.
        self.assertContains(response, "0 of 1")
        self.assertContains(response, f'data-phase="exclusion" data-run-id="{run.pk}"', html=False)

        # When the latest run is from before Parsifal kept what came before a run, no run can be undone.
        ScreeningRun.objects.update(undoable=False)
        response = self.client.get(self.list_url, {"review-id": self.review.pk})
        self.assertNotContains(response, ">Undo</button>", html=False)
        self.assertContains(response, "Made before Parsifal kept what came before a run")
        self.assertContains(response, f"Run {run.pk} and the runs before it were made before")

    def test_the_details(self):
        run = self.screen()
        response = self.client.get(self.run_url, {"review-id": self.review.pk, "run-id": run.pk})
        self.assertContains(response, f"Run {run.pk}")
        self.assertContains(response, "Not about &lt;software&gt; engineering")  # the criteria sent, escaped
        self.assertContains(response, "Be strict.")
        self.assertContains(response, "Edited")  # the context sent
        self.assertContains(response, "A study")
        self.assertContains(response, "Rejected")
        self.assertContains(response, "0.96")
        self.assertContains(response, "1 of 1 decisions")
        response = self.client.get(self.run_url, {"review-id": self.review.pk, "run-id": 999999})
        self.assertEqual(400, response.status_code)

    def test_undo(self):
        run = self.screen()
        response = self.client.get(self.undo_url, {"review-id": self.review.pk, "run-id": run.pk})
        self.assertContains(response, f"Undo run {run.pk}?")
        self.assertContains(response, "<strong>1</strong> study goes", html=False)
        self.assertContains(response, "(1 unclassified)")
        self.assertContains(response, "is removed (there was none before the run)")
        self.assertContains(response, "js-ai-undo-confirm")
        self.assertTrue(ScreeningRun.objects.filter(pk=run.pk).exists())  # nothing done yet

        response = self.client.post(self.undo_url, {"review-id": self.review.pk, "run-id": run.pk})
        self.assertContains(response, f"Run {run.pk} was undone")
        self.assertContains(response, "No AI runs yet.")
        self.article.refresh_from_db()
        self.assertEqual((Article.UNCLASSIFIED, None), (self.article.status, self.article.selection_criteria))
        self.assertFalse(StudyDecision.objects.exists())
        self.assertFalse(ScreeningRun.objects.exists())

        response = self.client.post(self.undo_url, {"review-id": self.review.pk, "run-id": run.pk})
        self.assertEqual(400, response.status_code)
        self.assertIn("not found", response.content.decode())

    def test_undo_one_run_after_another(self):
        older = self.screen()
        run = self.screen()
        response = self.client.get(self.undo_url, {"review-id": self.review.pk, "run-id": older.pk})
        self.assertEqual(400, response.status_code)
        self.assertIn(f"undo run {run.pk} first", response.content.decode())
        response = self.client.get(self.undo_url, {"review-id": self.review.pk, "run-id": run.pk})
        self.assertContains(response, f"run {older.pk} becomes the latest (it can be undone next)")
        response = self.client.post(self.undo_url, {"review-id": self.review.pk, "run-id": run.pk})
        self.assertContains(response, f"Run {run.pk} was undone")
        # The run before is the latest now, and what it did stands again.
        self.assertContains(response, f'data-run-id="{older.pk}">Undo</button>', html=False)
        self.assertContains(response, "1 of 1")
        self.client.post(self.undo_url, {"review-id": self.review.pk, "run-id": older.pk})
        self.article.refresh_from_db()
        self.assertEqual(Article.UNCLASSIFIED, self.article.status)
        self.assertFalse(StudyDecision.objects.exists())

    def test_undo_says_what_changed_since(self):
        run = self.screen()
        Article.objects.filter(pk=self.article.pk).update(status=Article.ACCEPTED, updated_at=timezone.now())
        response = self.client.get(self.undo_url, {"review-id": self.review.pk, "run-id": run.pk})
        self.assertContains(response, "<strong>1</strong> study whose status", html=False)
        self.assertContains(response, "since the run keeps the newer status.")
        self.assertNotContains(response, "go back to the status")
        self.client.post(self.undo_url, {"review-id": self.review.pk, "run-id": run.pk})
        self.article.refresh_from_db()
        self.assertEqual(Article.ACCEPTED, self.article.status)
        self.assertFalse(StudyDecision.objects.exists())

    def test_impact_before_starting(self):
        self.connect()
        data = {"review-id": self.review.pk, "reviewer-id": self.bot.pk, "phase": "exclusion", "statuses": ["R", "U"]}
        impact = self.client.post(self.impact_url, data).json()
        self.assertEqual((1, 0, False), (impact["studies"], impact["decisions"], impact["confirm"]))
        decisions.record_decision(review=self.review, article_id=self.article.pk, actor=self.bot, status="A")
        impact = self.client.post(self.impact_url, data).json()
        self.assertEqual((1, True), (impact["decisions"], impact["confirm"]))
        self.assertIn("While it is the latest run, it can be undone in AI runs.", impact["message"])
        response = self.client.post(self.impact_url, {**data, "reviewer-id": ""})
        self.assertEqual(400, response.status_code)
        self.assertIn("Choose the reviewer", response.json()["error"])

    def test_run_again_opens_the_window_with_its_settings(self):
        run = self.screen(threshold="0.75", statuses=["U"])
        response = self.client.get(
            self.form_url, {"review-id": self.review.pk, "phase": "inclusion", "run-id": run.pk}
        )
        self.assertContains(response, f"The settings of <strong>run {run.pk}</strong>", html=False)
        self.assertContains(response, "Exclude with AI")  # the run's phase, whatever the button said
        self.assertContains(response, 'value="0.75"', html=False)
        self.assertContains(response, f'<option value="{self.bot.pk}" selected>', html=False)
        self.assertContains(response, ">Be strict.</textarea>", html=False)
        self.assertContains(response, ">Edited</textarea>", html=False)  # the objective sent
        self.assertContains(response, 'name="statuses" value="U" checked', html=False)
        self.assertNotContains(response, 'name="statuses" value="R" checked', html=False)
        response = self.client.get(self.form_url, {"review-id": self.review.pk, "run-id": 999999})
        self.assertEqual(400, response.status_code)

    def test_members_only(self):
        run = self.screen()
        self.client.force_login(self.outsider)
        for url in (self.list_url, self.run_url, self.undo_url):
            response = self.client.get(url, {"review-id": self.review.pk, "run-id": run.pk})
            self.assertNotEqual(200, response.status_code)
        response = self.client.post(self.undo_url, {"review-id": self.review.pk, "run-id": run.pk})
        self.assertNotEqual(200, response.status_code)
        self.assertTrue(ScreeningRun.objects.filter(pk=run.pk).exists())
