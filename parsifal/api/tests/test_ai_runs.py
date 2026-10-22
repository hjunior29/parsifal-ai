from unittest import mock

from django.utils import timezone

from parsifal.api.tests.test_ai_screening import AiScreeningApiBase, answer
from parsifal.apps.core import jev
from parsifal.apps.reviews.models import Article, ScreeningRun, StudyDecision


class TestAiRunsApi(AiScreeningApiBase):
    def run_once(self, **payload):
        run = self.api("post", self.review_path("/ai-screening/runs"), {"reviewer_id": self.author.pk, **payload})
        self.assertEqual(201, run.status_code, run.content)
        run = run.json()
        with mock.patch.object(jev, "evaluate", side_effect=[answer(0.96, 0.04), answer(0.1, 0.9)]):
            self.api("post", self.review_path(f"/ai-screening/runs/{run['id']}/step"), {"size": 2})
        return run

    def impact(self, **payload):
        response = self.api("post", self.review_path("/ai-screening/impact"), payload)
        self.assertEqual(200, response.status_code, response.content)
        return response.json()

    def test_impact_rerun_and_undo(self):
        impact = self.impact(reviewer_id=self.author.pk)
        self.assertEqual(
            (2, 0, 0, False), (impact["studies"], impact["decisions"], impact["classified"], impact["confirm"])
        )

        run = self.run_once(threshold=0.8)
        listed = self.api("get", self.review_path("/ai-screening/runs")).json()[0]
        self.assertEqual(
            (run["id"], 2, True, ""), (listed["id"], listed["standing"], listed["undoable"], listed["undo_blocked"])
        )

        impact = self.impact(reviewer_id=self.author.pk)
        self.assertEqual((2, 1, True), (impact["decisions"], impact["classified"], impact["confirm"]))
        self.assertIn(f"rewrites 2 decisions of {self.author.username}", impact["message"])
        self.assertEqual(impact, self.impact(run_id=run["id"]))

        with self.subTest(msg="run again with the same settings, changing some"):
            response = self.api("post", self.review_path(f"/ai-screening/runs/{run['id']}/rerun"), {"statuses": ["U"]})
            self.assertEqual(201, response.status_code, response.content)
            again = response.json()
            self.assertEqual(
                (0.8, ["U"], 1), (again["parameters"]["threshold"], again["parameters"]["statuses"], again["total"])
            )
            self.assertEqual(self.author.pk, again["reviewer_id"])
            # The new run is the latest: undone first, the earlier one is the latest again.
            response = self.api("post", self.review_path(f"/ai-screening/runs/{again['id']}/undo"))
            self.assertEqual(200, response.status_code, response.content)

        with self.subTest(msg="what undoing would do, then undoing"):
            preview = self.api("get", self.review_path(f"/ai-screening/runs/{run['id']}/undo")).json()
            self.assertEqual(
                (2, 1, {"U": 1}, 0, 0, 2, 0),
                tuple(
                    preview[name]
                    for name in (
                        "screened",
                        "statuses_restored",
                        "back_to",
                        "statuses_kept",
                        "decisions_restored",
                        "decisions_removed",
                        "decisions_kept",
                    )
                ),
            )
            self.assertTrue(preview["message"].startswith(f"Undoing run {run['id']}: "))
            response = self.api("post", self.review_path(f"/ai-screening/runs/{run['id']}/undo"))
            self.assertEqual(200, response.status_code, response.content)
            self.assertTrue(response.json()["message"].startswith(f"Run {run['id']} was undone: "))
            self.secondary.refresh_from_db()
            self.assertEqual((Article.UNCLASSIFIED, None), (self.secondary.status, self.secondary.selection_criteria))
            self.assertFalse(StudyDecision.objects.filter(user=self.author).exists())
            self.assertEqual(404, self.api("get", self.review_path(f"/ai-screening/runs/{run['id']}")).status_code)
            self.assertEqual(
                404, self.api("post", self.review_path(f"/ai-screening/runs/{run['id']}/undo")).status_code
            )

    def test_who_and_when(self):
        run = self.run_once()
        undo = self.review_path(f"/ai-screening/runs/{run['id']}/undo")
        co_author = self.client_for(self.co_author)
        self.assertEqual(403, self.api("post", undo, client=co_author).status_code)
        self.assertEqual(403, self.api("get", undo, client=co_author).status_code)
        listed = self.api("get", self.review_path("/ai-screening/runs"), client=co_author).json()[0]
        self.assertEqual(False, listed["undoable"])
        self.assertIn("Only the main author", listed["undo_blocked"])
        self.assertEqual(404, self.api("post", undo, client=self.client_for(self.outsider)).status_code)

        busy = self.api("post", self.review_path("/ai-screening/runs"), {"reviewer_id": self.author.pk}).json()
        undo_busy = self.review_path(f"/ai-screening/runs/{busy['id']}/undo")
        ScreeningRun.objects.filter(pk=busy["id"]).update(last_step_at=timezone.now())
        response = self.api("post", undo_busy)
        self.assertEqual(409, response.status_code)
        self.assertIn("being screened right now", response.content.decode())

        # Only the latest run can be undone.
        ScreeningRun.objects.filter(pk=busy["id"]).update(last_step_at=None)
        response = self.api("post", undo)
        self.assertEqual(422, response.status_code)
        self.assertIn(f"undo run {busy['id']} first", response.content.decode())
        listed = {item["id"]: item for item in self.api("get", self.review_path("/ai-screening/runs")).json()}
        self.assertEqual((True, False), (listed[busy["id"]]["undoable"], listed[run["id"]]["undoable"]))
        self.assertIn("Only the latest run", listed[run["id"]]["undo_blocked"])
        self.assertEqual(200, self.api("post", undo_busy).status_code)

        ScreeningRun.objects.filter(pk=run["id"]).update(undoable=False)
        self.assertEqual(422, self.api("post", undo).status_code)
        detail = self.api("get", self.review_path(f"/ai-screening/runs/{run['id']}")).json()
        self.assertEqual((None, False), (detail["standing"], detail["undoable"]))
