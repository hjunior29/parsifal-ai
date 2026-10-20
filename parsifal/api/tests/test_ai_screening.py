from unittest import mock

from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.accounts.models import Integration
from parsifal.apps.core import jev
from parsifal.apps.reviews.models import Article, SelectionCriteria, StudyDecision
from parsifal.apps.reviews.services import ai_screening, screening_requests
from parsifal.apps.reviews.tests.factories import ArticleFactory

KEY = "fake-jev-key-0123456789abcdef"
MODELS = [
    {"name": "jev-1.13.0", "description": "Stable", "release_date": "2026-08-01"},
    {"name": "jev-1.14.0", "description": "Newest", "release_date": "2026-10-14"},
]


def answer(p_criteria, p_none, model="jev-1.13.0"):
    probabilities = {"E1": p_criteria, "none": p_none}
    return {
        "model": model,
        "answers": {"exclusion": {"type": "choice", "probabilities": probabilities}},
    }


class TestJevIntegrationApi(ApiTestCase):
    def test_set_show_test_and_remove(self):
        self.assertEqual(
            {"configured": False, "masked_key": None, "model": None, "updated_at": None},
            self.api("get", "/integrations/jev").json(),
        )
        self.assertEqual(422, self.api("put", "/integrations/jev", {"model": "jev-1.13.0"}).status_code)
        self.assertEqual(422, self.api("post", "/integrations/jev/test", {}).status_code)

        response = self.api("put", "/integrations/jev", {"api_key": f" {KEY} "})
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual((True, "…cdef", "jev-1.13.0"), (body["configured"], body["masked_key"], body["model"]))
        self.assertNotIn(KEY, response.content.decode())
        self.assertEqual(KEY, Integration.objects.get(user=self.author).api_key)

        with self.subTest(msg="blank key keeps the saved one"):
            body = self.api("put", "/integrations/jev", {"api_key": "", "model": "jev-1.14.0"}).json()
            self.assertEqual(("…cdef", "jev-1.14.0"), (body["masked_key"], body["model"]))
            self.assertEqual(422, self.api("put", "/integrations/jev", {"model": "m" * 101}).status_code)

        with self.subTest(msg="test the key"):
            card = {"name": "jev-1.13.0", "description": "Stable", "release_date": "2026-08-01"}
            with mock.patch.object(jev, "list_models", return_value=[card]) as list_models:
                response = self.api("post", "/integrations/jev/test", {})
            self.assertEqual({"models": [card]}, response.json())
            list_models.assert_called_once_with(KEY)
            with mock.patch.object(jev, "list_models", return_value=[card]) as list_models:
                response = self.api("post", "/integrations/jev/test", {"api_key": "fake-unsaved-key-1111"})
            list_models.assert_called_once_with("fake-unsaved-key-1111")
            self.assertEqual(KEY, Integration.objects.get(user=self.author).api_key)  # nothing saved
            rejected = jev.JevError("Jev rejected the API key.", status=401, fatal=True)
            with mock.patch.object(jev, "list_models", side_effect=rejected):
                response = self.api("post", "/integrations/jev/test", {})
            self.assertEqual((422, "api_key"), (response.status_code, response.json()["field"]))
            with mock.patch.object(jev, "list_models", side_effect=jev.JevError("Could not reach Jev (Timeout).")):
                response = self.api("post", "/integrations/jev/test", {})
            self.assertEqual((502, "upstream_error"), (response.status_code, response.json()["code"]))

        with self.subTest(msg="per user"):
            self.assertFalse(
                self.api("get", "/integrations/jev", client=self.client_for(self.co_author)).json()["configured"]
            )

        self.assertEqual(204, self.api("delete", "/integrations/jev").status_code)
        self.assertFalse(Integration.objects.filter(user=self.author).exists())
        self.assertEqual(204, self.api("delete", "/integrations/jev").status_code)


class AiScreeningApiBase(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.criteria = SelectionCriteria.objects.create(
            review=cls.review, criteria_type="E", description="Not a primary study"
        )
        cls.review.objective = "Find screening tools."
        cls.review.save()

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(jev, "list_models", return_value=MODELS)  # setup asks Jev for its models
        self.list_models = patcher.start()
        self.addCleanup(patcher.stop)
        Integration.objects.create(user=self.author, provider=Integration.JEV, api_key=KEY, model="jev-1.13.0")
        self.secondary = ArticleFactory(review=self.review, source=self.source, title="A survey", abstract="x")
        self.primary = ArticleFactory(review=self.review, source=self.source, title="An experiment", abstract="y")


class TestAiScreeningApi(AiScreeningApiBase):
    def test_setup(self):
        body = self.api("get", self.review_path("/ai-screening")).json()
        self.assertEqual((True, "jev-1.13.0"), (body["configured"], body["model"]))
        self.assertEqual("Find screening tools.", body["context"]["objective"])
        self.assertEqual(
            [{"key": "E1", "id": self.criteria.pk, "description": "Not a primary study"}], body["criteria"]
        )
        self.assertEqual("choice", body["question_type"])
        default = screening_requests.default("exclusion")
        self.assertEqual((default, default), (body["template"], body["template_default"]))
        self.assertIn({"name": "study.abstract", "description": "The study's abstract."}, body["placeholders"])
        self.assertEqual(
            (0.9, 0.5, 0.99, 8, 50),
            tuple(
                body[k]
                for k in ("threshold_default", "threshold_min", "threshold_max", "step_size_default", "step_size_max")
            ),
        )
        by_status = {"A": 0, "R": 0, "U": 2, "D": 0}
        self.assertEqual(
            [
                {"source_id": None, "name": "All sources", "studies": 2, "by_status": by_status},
                {"source_id": self.source.pk, "name": self.source.name, "studies": 2, "by_status": by_status},
            ],
            body["scopes"],
        )
        self.assertEqual(
            (["A", "R", "U", "D"], ["R", "U"]),
            ([status["status"] for status in body["statuses"]], body["statuses_default"]),
        )
        self.assertEqual((MODELS, ""), (body["models"], body["models_error"]))
        self.assertEqual({self.author.pk, self.co_author.pk}, {reviewer["id"] for reviewer in body["reviewers"]})
        self.assertIsNone(body["reviewer_id"])

        other = self.api("get", self.review_path("/ai-screening"), client=self.client_for(self.co_author)).json()
        self.assertEqual((False, None, []), (other["configured"], other["model"], other["models"]))
        self.assertEqual([self.co_author.pk], [reviewer["id"] for reviewer in other["reviewers"]])
        self.assertEqual(
            404, self.api("get", self.review_path("/ai-screening"), client=self.client_for(self.outsider)).status_code
        )

    def test_start_step_results_and_runs(self):
        response = self.api(
            "post",
            self.review_path("/ai-screening/runs"),
            {"guidance": "Be strict.", "objective": "Edited", "reviewer_id": self.co_author.pk, "model": "jev-1.14.0"},
        )
        self.assertEqual(201, response.status_code, response.content)
        run = response.json()
        self.assertEqual(
            ("running", 2, 0, "jev-1.14.0"), (run["status"], run["total"], run["processed"], run["model"])
        )
        self.assertEqual((self.co_author.pk, self.co_author.username), (run["reviewer_id"], run["reviewer"]))
        self.assertEqual(
            ("Edited", ["R", "U"]), (run["parameters"]["context"]["objective"], run["parameters"]["statuses"])
        )
        setup = self.api("get", self.review_path("/ai-screening")).json()
        self.assertEqual(
            ("Find screening tools.", self.co_author.pk), (setup["context"]["objective"], setup["reviewer_id"])
        )
        self.assertEqual(self.author.username, run["started_by"])

        with mock.patch.object(jev, "evaluate", side_effect=[answer(0.96, 0.04), answer(0.1, 0.9)]):
            response = self.api("post", self.review_path(f"/ai-screening/runs/{run['id']}/step"), {"size": 2})
        self.assertEqual(200, response.status_code, response.content)
        step = response.json()
        self.assertEqual(("finished", 1, 1), (step["run"]["status"], step["run"]["excluded"], step["run"]["passed"]))
        rejected = step["results"][0]
        self.assertEqual(
            (self.secondary.pk, "A survey", "excluded", 0.96, "E1", self.criteria.pk),
            tuple(
                rejected[k]
                for k in ("article_id", "title", "outcome", "p_exclude", "criteria_key", "selection_criteria_id")
            ),
        )
        self.assertEqual(({"E1": 0.96, "none": 0.04}, "U"), (rejected["probabilities"], rejected["previous_status"]))

        self.secondary.refresh_from_db()
        self.assertEqual(
            (Article.REJECTED, self.criteria, self.co_author),
            (self.secondary.status, self.secondary.selection_criteria, self.secondary.updated_by),
        )
        self.assertEqual(
            {self.secondary.pk: "R", self.primary.pk: "U"},
            dict(StudyDecision.objects.filter(user=self.co_author).values_list("article_id", "status")),
        )

        with self.subTest(msg="results, filtered and paginated"):
            page = self.api(
                "get", self.review_path(f"/ai-screening/runs/{run['id']}/results"), QUERY_STRING="outcome=passed"
            ).json()
            self.assertEqual(
                (1, self.primary.pk, None),
                (page["count"], page["items"][0]["article_id"], page["items"][0]["criteria_key"]),
            )
            self.assertEqual(
                2, self.api("get", self.review_path(f"/ai-screening/runs/{run['id']}/results")).json()["count"]
            )
            self.assertEqual(
                422,
                self.api(
                    "get", self.review_path(f"/ai-screening/runs/{run['id']}/results"), QUERY_STRING="outcome=maybe"
                ).status_code,
            )

        with self.subTest(msg="runs and one run"):
            runs = self.api("get", self.review_path("/ai-screening/runs")).json()
            self.assertEqual([(run["id"], "finished")], [(r["id"], r["status"]) for r in runs])
            detail = self.api("get", self.review_path(f"/ai-screening/runs/{run['id']}")).json()
            self.assertEqual(
                ("Be strict.", 0.9), (detail["parameters"]["guidance"], detail["parameters"]["threshold"])
            )
            self.assertIsNotNone(detail["finished_at"])

    def test_validation_and_continuing(self):
        start = self.review_path("/ai-screening/runs")
        me = {"reviewer_id": self.author.pk}
        self.assertEqual(422, self.api("post", start, {"threshold": 0.2, **me}).status_code)
        self.assertEqual(422, self.api("post", start, {}).status_code)  # reviewer_id is required
        self.assertEqual(422, self.api("post", start, {"model": "jev-9", **me}).status_code)
        self.assertEqual(422, self.api("post", start, {"statuses": ["X"], **me}).status_code)
        no_studies = self.api("post", start, {"statuses": ["A", "D"], **me})
        self.assertEqual(422, no_studies.status_code)
        self.assertIn("no studies with these statuses", no_studies.json()["detail"])
        co_author = self.client_for(self.co_author)
        no_key = self.api("post", start, {"reviewer_id": self.co_author.pk}, client=co_author)
        self.assertEqual(422, no_key.status_code)
        self.assertIn("Settings → Integrations", no_key.json()["detail"])
        Integration.objects.create(user=self.co_author, provider=Integration.JEV, api_key=KEY, model="jev-1.13.0")
        self.assertEqual(403, self.api("post", start, me, client=co_author).status_code)  # only as themselves
        self.assertEqual(404, self.api("post", start, {"reviewer_id": self.outsider.pk}).status_code)

        run = self.api("post", start, {"source_id": self.source.pk, **me}).json()
        self.assertEqual(
            422, self.api("post", self.review_path(f"/ai-screening/runs/{run['id']}/step"), {"size": 51}).status_code
        )
        with self.subTest(msg="setup shows the unfinished run; stepping it continues"):
            setup = self.api("get", self.review_path("/ai-screening")).json()
            self.assertEqual(
                (run["id"], "running", False),
                (setup["unfinished_run"]["id"], setup["unfinished_run"]["status"], setup["unfinished_run_active"]),
            )
            with mock.patch.object(jev, "evaluate", side_effect=[answer(0.1, 0.9), answer(0.1, 0.9)]):
                step = self.api("post", self.review_path(f"/ai-screening/runs/{run['id']}/step"), {}).json()
            self.assertEqual(("finished", 2), (step["run"]["status"], step["run"]["passed"]))
            self.assertIsNone(self.api("get", self.review_path("/ai-screening")).json()["unfinished_run"])

        with self.subTest(msg="there is no cancel: a new run discards an unfinished one"):
            self.assertEqual(
                404, self.api("post", self.review_path(f"/ai-screening/runs/{run['id']}/cancel")).status_code
            )
            left = self.api("post", start, me).json()
            self.api("post", start, me)
            self.assertEqual(
                "cancelled", self.api("get", self.review_path(f"/ai-screening/runs/{left['id']}")).json()["status"]
            )

        self.assertEqual(404, self.api("get", self.review_path("/ai-screening/runs/999999")).status_code)
        self.assertEqual(
            404,
            self.api(
                "post",
                self.review_path(f"/ai-screening/runs/{run['id']}/step"),
                {},
                client=self.client_for(self.outsider),
            ).status_code,
        )


class TestRequestTemplateApi(AiScreeningApiBase):
    def test_preview_and_start_with_a_template(self):
        preview = self.review_path("/ai-screening/preview")
        response = self.api("post", preview, {})
        self.assertEqual(200, response.status_code, response.content)
        body = response.json()
        self.assertEqual((self.secondary.pk, "A survey"), (body["article_id"], body["title"]))
        self.assertEqual("jev-1.13.0", body["request"]["model"])
        self.assertEqual({"title": "A survey", "abstract": "x"}, body["request"]["state"]["study"])
        self.assertEqual("Not a primary study", body["request"]["questions"]["exclusion"]["criteria"]["E1"])

        edited = screening_requests.default("exclusion")
        edited["state"] = {"study": "{{study}}", "review": "{{review}}"}
        body = self.api("post", preview, {"template": edited, "article_id": self.primary.pk}).json()
        self.assertEqual(
            {
                "study": {"title": "An experiment", "abstract": "y"},
                "review": {"title": self.review.title, "objective": "Find screening tools."},
            },
            body["request"]["state"],
        )
        self.assertEqual("An experiment", body["title"])

        start = self.review_path("/ai-screening/runs")
        response = self.api("post", start, {"reviewer_id": self.author.pk, "template": edited})
        self.assertEqual(201, response.status_code, response.content)
        self.assertEqual(edited, response.json()["parameters"]["template"])
        self.assertEqual(edited, self.api("get", self.review_path("/ai-screening")).json()["template"])
        response = self.api(
            "post", start, {"reviewer_id": self.author.pk, "template": screening_requests.as_text(edited)}
        )
        self.assertEqual(201, response.status_code, response.content)

        refused = self.api("post", start, {"reviewer_id": self.author.pk, "template": {"state": {}, "question": {}}})
        self.assertEqual((422, "template"), (refused.status_code, refused.json()["field"]))
        self.assertIn('keep "type": "choice"', refused.json()["detail"])
        refused = self.api("post", preview, {"template": "{"})
        self.assertEqual((422, "template"), (refused.status_code, refused.json()["field"]))
        self.assertEqual(404, self.api("post", preview, {}, client=self.client_for(self.outsider)).status_code)


def inclusion_answer(meets, model="jev-1.13.0"):
    return {"model": model, "answers": {"inclusion_I1": {"type": "noul", "noul": meets}}}


class TestIncludeWithAiApi(AiScreeningApiBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.inclusion = SelectionCriteria.objects.create(
            review=cls.review, criteria_type="I", description="Implemented tool"
        )

    def test_setup_for_inclusion(self):
        body = self.api("get", self.review_path("/ai-screening"), QUERY_STRING="phase=inclusion").json()
        self.assertEqual("inclusion", body["phase"])
        self.assertEqual([{"key": "I1", "id": self.inclusion.pk, "description": "Implemented tool"}], body["criteria"])
        self.assertEqual("noul", body["question_type"])
        self.assertEqual((0.5, 0.99), (body["threshold_min"], body["threshold_max"]))
        self.assertNotIn("reject_threshold_min", body)
        self.assertEqual(screening_requests.default("inclusion"), body["template"])
        self.assertEqual(["A", "U"], body["statuses_default"])
        self.assertEqual(2, body["scopes"][0]["studies"])
        exclusion = self.api("get", self.review_path("/ai-screening")).json()
        self.assertEqual(
            ("exclusion", "choice", ["R", "U"]),
            (exclusion["phase"], exclusion["question_type"], exclusion["statuses_default"]),
        )
        self.assertEqual(
            422, self.api("get", self.review_path("/ai-screening"), QUERY_STRING="phase=maybe").status_code
        )

    def test_inclusion_run(self):
        start = self.review_path("/ai-screening/runs")
        inclusion = {"reviewer_id": self.author.pk, "phase": "inclusion"}
        refused = self.api("post", start, {**inclusion, "thresholds": {"I1": 0.2}})
        self.assertEqual((422, "thresholds"), (refused.status_code, refused.json()["field"]))
        self.assertIn("The threshold of I1 must be between 0.5 and 0.99", refused.json()["detail"])
        refused = self.api("post", start, {"reviewer_id": self.author.pk, "thresholds": ["E1=0.9"]})
        self.assertIn("Per-criterion thresholds are for Include with AI", refused.json()["detail"])
        response = self.api("post", start, {**inclusion, "thresholds": ["I1=0.85"]})
        self.assertEqual(201, response.status_code, response.content)
        run = response.json()
        self.assertEqual(("inclusion", 2, ["A", "U"]), (run["phase"], run["total"], run["parameters"]["statuses"]))
        self.assertEqual({"I1": 0.85}, run["parameters"]["thresholds"])
        setup = self.api("get", self.review_path("/ai-screening"), QUERY_STRING="phase=inclusion").json()
        self.assertEqual({"I1": 0.85}, setup["thresholds"])
        self.assertEqual({}, self.api("get", self.review_path("/ai-screening")).json()["thresholds"])

        with (
            mock.patch.object(ai_screening, "WORKERS", 1),
            mock.patch.object(jev, "evaluate", side_effect=[inclusion_answer(0.05), inclusion_answer(0.96)]),
        ):
            step = self.api("post", self.review_path(f"/ai-screening/runs/{run['id']}/step"), {"size": 2}).json()
        self.assertEqual(
            ("finished", 1, 0, 1), tuple(step["run"][k] for k in ("status", "included", "excluded", "undecided"))
        )
        undecided, accepted = step["results"]
        self.assertEqual(
            ("undecided", None, None, 0.05),
            (undecided["outcome"], undecided["criteria_key"], undecided["p_exclude"], undecided["p_include"]),
        )
        self.assertEqual({"I1": 0.96}, accepted["probabilities"])
        self.assertEqual(
            {self.secondary.pk: "U", self.primary.pk: "A"},  # Include with AI never rejects
            dict(StudyDecision.objects.filter(user=self.author).values_list("article_id", "status")),
        )
        self.primary.refresh_from_db()
        self.secondary.refresh_from_db()
        self.assertEqual((Article.ACCEPTED, Article.UNCLASSIFIED), (self.primary.status, self.secondary.status))
        self.assertEqual(
            1,
            self.api(
                "get", self.review_path(f"/ai-screening/runs/{run['id']}/results"), QUERY_STRING="outcome=included"
            ).json()["count"],
        )
        self.assertEqual(
            422,
            self.api(
                "post", self.review_path("/ai-screening/runs"), {"reviewer_id": self.author.pk, "phase": "maybe"}
            ).status_code,
        )
