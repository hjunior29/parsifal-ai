import json
import re
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from parsifal.apps.accounts.models import Integration
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core import jev
from parsifal.apps.reviews.models import Article, ScreeningRun, SelectionCriteria, StudyDecision
from parsifal.apps.reviews.services import agents, ai_screening
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory, SourceFactory

MODELS = [
    {"name": "jev-1.13.0", "description": "Stable", "release_date": "2026-08-01"},
    {"name": "jev-1.14.0", "description": "Newest", "release_date": "2026-10-14"},
]

EXCLUDE = {
    "model": "jev-1.13.0",
    "answers": {f"exclusion_{n}": {"type": "choice", "probabilities": {"E1": 0.96, "none": 0.04}} for n in (1, 2)},
}


class AiScreeningViewsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source], objective="Our objective & scope")
        cls.owner = cls.review.author
        cls.outsider = UserFactory()
        cls.criteria = SelectionCriteria.objects.create(
            review=cls.review, criteria_type="E", description="Not about <software> engineering"
        )
        cls.article = ArticleFactory(review=cls.review, source=cls.source, title="A study", abstract="Text")
        cls.bot = agents.create_agent(review=cls.review, actor=cls.owner, name="Screener").agent.user
        cls.form_url = reverse("reviews:conducting:ai_screening")
        cls.start_url = reverse("reviews:conducting:ai_screening_start")
        cls.step_url = reverse("reviews:conducting:ai_screening_step")

    def setUp(self):
        self.client.force_login(self.owner)
        # The window asks Jev for its models when it opens: never reach the network in tests.
        patcher = mock.patch.object(jev, "list_models", return_value=MODELS)
        self.list_models = patcher.start()
        self.addCleanup(patcher.stop)

    def connect(self):
        Integration.objects.create(user=self.owner, provider=Integration.JEV, api_key="fake-key", model="jev-1.13.0")

    def start(self, **extra):
        data = {
            "review-id": self.review.pk,
            "reviewer-id": self.bot.pk,
            "model": "jev-1.13.0",
            "context-objective": "Edited",
            "threshold": "0.9",
            "source-id": "",
            "statuses": ["R", "U"],
        }
        data.update(extra)
        return self.client.post(self.start_url, data)

    def test_button_on_the_all_sources_tab(self):
        response = self.client.get(
            reverse("reviews:conducting:source_articles"), {"review-id": self.review.pk, "source-id": "None"}
        )
        self.assertContains(response, "btn-ai-screening")
        self.assertContains(response, "Exclude with AI")

    def test_asks_for_the_key_first(self):
        response = self.client.get(self.form_url, {"review-id": self.review.pk})
        self.assertContains(response, reverse("settings:integrations"))
        self.assertNotContains(response, "ai-screening-form")

    def test_asks_for_exclusion_criteria_first(self):
        self.connect()
        empty = ReviewFactory(author=self.owner)
        response = self.client.get(self.form_url, {"review-id": empty.pk})
        self.assertContains(response, "The review has no exclusion criteria")

    def test_setup_window_is_prefilled_and_criteria_are_read_only(self):
        self.connect()
        response = self.client.get(self.form_url, {"review-id": self.review.pk})
        self.assertContains(response, 'id="ai-screening-form"')
        self.assertContains(response, "Our objective &amp; scope")
        self.assertContains(response, "<code>E1</code> Not about &lt;software&gt; engineering", html=False)
        self.assertNotContains(response, 'name="criteria')
        self.assertNotContains(response, 'name="rescreen"')
        script = re.search(r'id="ai-screening-counts"[^>]*>(.*?)</script>', response.content.decode())
        counts = json.loads(script.group(1))
        unclassified = {"A": 0, "R": 0, "U": 1, "D": 0}
        self.assertEqual({"": unclassified, str(self.source.pk): unclassified}, counts)

        with self.subTest(msg="statuses to send: rejected and unclassified by default"):
            for code, checked in (("A", False), ("R", True), ("U", True), ("D", False)):
                self.assertContains(
                    response,
                    f'<input type="checkbox" name="statuses" value="{code}"{" checked" if checked else ""}>',
                    html=False,
                )
            self.assertContains(response, "js-ai-all-statuses")

        with self.subTest(msg="reviewers to choose from, none preselected before the first run"):
            self.assertContains(response, '<option value="">Choose the reviewer…</option>', html=True)
            self.assertContains(
                response,
                f'<option value="{self.bot.pk}">Screener ({self.bot.username}) · AI agent</option>',
                html=True,
            )
            self.assertContains(response, f"({self.owner.username}) · you")

        with self.subTest(msg="models listed by Jev when the window opens, the default selected"):
            self.list_models.assert_called_with("fake-key", quick=True)
            self.assertContains(
                response, '<option value="jev-1.13.0" selected>jev-1.13.0 — Stable · 2026-08-01</option>', html=True
            )
            self.assertContains(
                response, '<option value="jev-1.14.0">jev-1.14.0 — Newest · 2026-10-14</option>', html=True
            )

        with self.subTest(msg="Jev unreachable: a text field with the default model"):
            self.list_models.side_effect = jev.JevError("Could not reach Jev (Timeout).")
            response = self.client.get(self.form_url, {"review-id": self.review.pk})
            self.assertContains(
                response, 'name="model" id="ai-model" class="form-control input-sm" value="jev-1.13.0"'
            )
            self.assertContains(response, "Could not load the list of models from Jev")

    def test_members_only(self):
        self.client.force_login(self.outsider)
        self.assertEqual(403, self.client.get(self.form_url, {"review-id": self.review.pk}).status_code)
        self.assertEqual(403, self.start().status_code)

    def test_start_errors_are_json(self):
        response = self.start()
        self.assertEqual(400, response.status_code)
        self.assertIn("Settings → Integrations", response.json()["error"])
        self.connect()
        response = self.start(threshold="0.2")
        self.assertEqual(400, response.status_code)
        self.assertIn("between 0.5 and 0.99", response.json()["error"])
        response = self.start(**{"reviewer-id": ""})
        self.assertIn("Choose the reviewer", response.json()["error"])
        response = self.start(statuses=[])
        self.assertIn("Choose the statuses", response.json()["error"])
        response = self.start(statuses=["A", "D"])
        self.assertIn("no studies with these statuses", response.json()["error"])

    def test_start_step_and_done(self):
        self.connect()
        response = self.start(guidance="Be strict.")
        self.assertEqual(200, response.status_code, response.content)
        run = response.json()["run"]
        self.assertEqual(("running", 1, 0), (run["status"], run["total"], run["processed"]))
        parameters = ScreeningRun.objects.get(pk=run["id"]).parameters
        self.assertEqual(("Edited", ["R", "U"]), (parameters["context"]["objective"], parameters["statuses"]))

        with mock.patch.object(jev, "evaluate", return_value=EXCLUDE):
            response = self.client.post(self.step_url, {"review-id": self.review.pk, "run-id": run["id"]})
        body = response.json()
        self.assertEqual(
            ("finished", 1, 1), (body["run"]["status"], body["run"]["excluded"], body["run"]["processed"])
        )
        self.assertEqual(
            [{"title": "A study", "outcome": "excluded", "p_exclude": 0.96, "criteria": "E1", "error": ""}],
            body["results"],
        )
        self.article.refresh_from_db()
        self.assertEqual(
            (Article.REJECTED, self.criteria, self.bot),
            (self.article.status, self.article.selection_criteria, self.article.updated_by),
        )
        self.assertEqual("R", StudyDecision.objects.get(article=self.article, user=self.bot).status)

        with self.subTest(msg="the next window preselects the last reviewer"):
            response = self.client.get(self.form_url, {"review-id": self.review.pk})
            self.assertContains(response, f'<option value="{self.bot.pk}" selected>', html=False)

    def test_an_unfinished_run_is_offered_to_continue(self):
        self.connect()
        response = self.client.get(self.form_url, {"review-id": self.review.pk})
        self.assertNotContains(response, 'js-ai-continue"', html=False)  # nothing unfinished yet
        self.assertNotContains(response, "Stop")

        run = self.start().json()["run"]  # the page was closed before the first step
        response = self.client.get(self.form_url, {"review-id": self.review.pk})
        self.assertContains(response, "stopped at")
        self.assertContains(response, "0 of 1 studies")
        self.assertContains(response, "Starting a new run below discards it.")
        script = re.search(r'id="ai-screening-unfinished"[^>]*>(.*?)</script>', response.content.decode())
        self.assertEqual(
            (run["id"], "running"), (json.loads(script.group(1))["id"], json.loads(script.group(1))["status"])
        )

        with self.subTest(msg="continuing is stepping the same run"):
            with mock.patch.object(jev, "evaluate", return_value=EXCLUDE):
                body = self.client.post(self.step_url, {"review-id": self.review.pk, "run-id": run["id"]}).json()
            self.assertEqual(("finished", 1), (body["run"]["status"], body["run"]["excluded"]))

    def test_a_run_driven_elsewhere_is_not_offered(self):
        self.connect()
        ArticleFactory(review=self.review, source=self.source, title="Another", abstract="x")
        run = ScreeningRun.objects.get(pk=self.start().json()["run"]["id"])
        with mock.patch.object(jev, "evaluate", return_value=EXCLUDE):
            ai_screening.process_step(run=run, actor=self.owner, size=1)  # another window drives it
        response = self.client.get(self.form_url, {"review-id": self.review.pk})
        self.assertContains(response, "is in progress in")
        self.assertNotContains(response, "js-ai-continue btn", html=False)
        self.assertNotContains(response, 'class="btn btn-warning btn-sm js-ai-continue"', html=False)

    def test_interruptions_are_reported_and_unknown_runs_rejected(self):
        self.connect()
        run = self.start().json()["run"]
        error = jev.JevError("Jev rejected the API key. Update it in Settings → Integrations.", status=401, fatal=True)
        with mock.patch.object(jev, "evaluate", side_effect=error):
            body = self.client.post(self.step_url, {"review-id": self.review.pk, "run-id": run["id"]}).json()
        self.assertEqual(("running", [], 0), (body["run"]["status"], body["results"], body["run"]["processed"]))
        self.assertIn("rejected the API key", body["run"]["error"])
        response = self.client.post(self.step_url, {"review-id": self.review.pk, "run-id": 999999})
        self.assertEqual(400, response.status_code)
        self.assertIn("not found", response.json()["error"])
        self.assertFalse(hasattr(views_module(), "ai_screening_cancel"))


def views_module():
    from parsifal.apps.reviews.conducting import views

    return views
