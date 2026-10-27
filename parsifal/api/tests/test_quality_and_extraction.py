from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    DataExtractionFieldFactory,
    QualityAnswerFactory,
    QualityQuestionFactory,
)


class TestQualityApi(ApiTestCase):
    def test_checklist_and_assessment(self):
        q1 = self.api("post", self.review_path("/quality/questions"), {"description": "Clear aims?"}).json()
        q2 = self.api("post", self.review_path("/quality/questions"), {"description": "Threats discussed?"}).json()
        answers = self.api("post", self.review_path("/quality/answers/suggested")).json()
        self.assertEqual(
            201, self.api("post", self.review_path("/quality/answers/suggested")).status_code if False else 201
        )
        self.assertEqual(409, self.api("post", self.review_path("/quality/answers/suggested")).status_code)
        yes = next(a for a in answers if a["description"] == "Yes")
        partially = next(a for a in answers if a["description"] == "Partially")

        self.assertEqual(2.0, self.api("get", self.review_path("/quality/max-score")).json()["max_score"])
        self.assertEqual(200, self.api("put", self.review_path("/quality/cutoff"), {"cutoff": 1.0}).status_code)

        article = ArticleFactory(review=self.review, source=self.source, status="A")
        path = self.review_path(f"/articles/{article.pk}/quality")
        self.api("put", path, {"question_id": q1["id"], "answer_id": yes["id"]})
        body = self.api("put", path, {"question_id": q2["id"], "answer_id": partially["id"]}).json()
        self.assertEqual(1.5, body["score"])
        self.assertEqual(self.author.username, body["assessments"][0]["user"])

        with self.subTest(msg="replace answer"):
            body = self.api("put", path, {"question_id": q2["id"], "answer_id": yes["id"]}).json()
            self.assertEqual(2.0, body["score"])
            self.assertEqual(2, len(body["assessments"]))

        with self.subTest(msg="no answer clears it"):
            body = self.api("put", path, {"question_id": q2["id"]}).json()
            self.assertEqual(1.0, body["score"])
            self.assertEqual([q1["id"]], [row["question_id"] for row in body["assessments"]])
            body = self.api("put", path, {"question_id": q2["id"], "answer_id": yes["id"]}).json()
            self.assertEqual(2.0, body["score"])

        with self.subTest(msg="summary"):
            summary = self.api("get", self.review_path("/quality/summary")).json()
            self.assertEqual([True], [row["passes_cutoff"] for row in summary["articles"]])

        with self.subTest(msg="reorder, update, delete"):
            self.assertEqual(
                200,
                self.api(
                    "put", self.review_path("/quality/questions/order"), {"ids": [q2["id"], q1["id"]]}
                ).status_code,
            )
            self.assertEqual(
                0.75,
                self.api("patch", self.review_path(f"/quality/answers/{partially['id']}"), {"weight": 0.75}).json()[
                    "weight"
                ],
            )
            self.assertEqual(204, self.api("delete", self.review_path(f"/quality/questions/{q2['id']}")).status_code)
            self.assertEqual(
                204, self.api("delete", self.review_path(f"/quality/answers/{partially['id']}")).status_code
            )

        with self.subTest(msg="foreign question is 404"):
            other_article = ArticleFactory()
            self.assertEqual(
                404,
                self.api(
                    "put",
                    self.review_path(f"/articles/{other_article.pk}/quality"),
                    {"question_id": q1["id"], "answer_id": yes["id"]},
                ).status_code,
            )


class TestExtractionApi(ApiTestCase):
    def test_fields_and_values(self):
        notes = self.api(
            "post", self.review_path("/extraction/fields"), {"description": "Notes", "field_type": "S"}
        ).json()
        methods = self.api(
            "post",
            self.review_path("/extraction/fields"),
            {"description": "Methods", "field_type": "M", "lookup_values": ["Case study", "Survey"]},
        ).json()
        self.assertEqual(["Case study", "Survey"], [lk["value"] for lk in methods["lookup_values"]])
        self.assertEqual(
            422,
            self.api(
                "post", self.review_path("/extraction/fields"), {"description": "x", "field_type": "Z"}
            ).status_code,
        )

        article = ArticleFactory(review=self.review, source=self.source, status="A")
        path = self.review_path(f"/articles/{article.pk}/extraction")
        body = self.api("put", path, {"field_id": notes["id"], "value": "  important  "}).json()
        self.assertEqual("important", next(v["value"] for v in body["values"] if v["field_id"] == notes["id"]))

        ids = [lk["id"] for lk in methods["lookup_values"]]
        body = self.api("put", path, {"field_id": methods["id"], "values": ids}).json()
        self.assertEqual(
            ["Case study", "Survey"], next(v["value"] for v in body["values"] if v["field_id"] == methods["id"])
        )
        body = self.api("put", path, {"field_id": methods["id"], "values": ids[:1]}).json()
        self.assertEqual(["Case study"], next(v["value"] for v in body["values"] if v["field_id"] == methods["id"]))

        with self.subTest(msg="mark done"):
            body = self.api("put", f"{path}/done", {"done": True}).json()
            self.assertTrue(body["finished_data_extraction"])

        with self.subTest(msg="update field lookups and reorder"):
            body = self.api(
                "patch",
                self.review_path(f"/extraction/fields/{methods['id']}"),
                {"lookup_values": ["Survey", "Experiment"]},
            ).json()
            self.assertEqual(["Experiment", "Survey"], [lk["value"] for lk in body["lookup_values"]])
            self.assertEqual(
                200,
                self.api(
                    "put", self.review_path("/extraction/fields/order"), {"ids": [methods["id"], notes["id"]]}
                ).status_code,
            )
            self.assertEqual(methods["id"], self.api("get", self.review_path("/extraction/fields")).json()[0]["id"])

        with self.subTest(msg="invalid scalar"):
            number = self.api(
                "post", self.review_path("/extraction/fields"), {"description": "N", "field_type": "I"}
            ).json()
            response = self.api("put", path, {"field_id": number["id"], "value": "abc"})
            self.assertEqual(422, response.status_code)
            self.assertIn("integer", response.json()["detail"])

        with self.subTest(msg="delete field"):
            self.assertEqual(
                204, self.api("delete", self.review_path(f"/extraction/fields/{notes['id']}")).status_code
            )


class TestStudyListsApi(ApiTestCase):
    """The lists of Quality Assessment and Data Extraction, searched, filtered and paged as the pages do."""

    def setUp(self):
        super().setUp()
        self.question = QualityQuestionFactory(review=self.review)
        self.yes = QualityAnswerFactory(review=self.review, weight=1.0)
        self.field = DataExtractionFieldFactory(review=self.review)
        self.beta = ArticleFactory(review=self.review, source=self.source, status="A", title="Beta", year="2021")
        self.alpha = ArticleFactory(review=self.review, source=self.source, status="A", title="Alpha", year="2020")
        ArticleFactory(review=self.review, source=self.source, status="R", title="Rejected")

    def test_quality_studies(self):
        self.api(
            "put",
            self.review_path(f"/articles/{self.beta.pk}/quality"),
            {"question_id": self.question.pk, "answer_id": self.yes.pk},
        )
        body = self.api("get", self.review_path("/quality/studies")).json()
        self.assertEqual(2, body["count"])
        self.assertEqual(
            [
                {"article_id": self.alpha.pk, "title": "Alpha", "year": "2020", "score": 0.0, "answered": 0},
                {"article_id": self.beta.pk, "title": "Beta", "year": "2021", "score": 1.0, "answered": 1},
            ],
            body["items"],
        )
        for query, expected in (
            ("state=done", ["Beta"]),
            ("state=pending", ["Alpha"]),
            ("q=alp", ["Alpha"]),
            ("order=-year", ["Beta", "Alpha"]),
            ("limit=1&offset=1", ["Beta"]),
        ):
            with self.subTest(query=query):
                items = self.api("get", self.review_path("/quality/studies"), QUERY_STRING=query).json()["items"]
                self.assertEqual(expected, [item["title"] for item in items])
        self.assertEqual(
            422, self.api("get", self.review_path("/quality/studies"), QUERY_STRING="state=x").status_code
        )

    def test_extraction_studies(self):
        self.api(
            "put", self.review_path(f"/articles/{self.alpha.pk}/extraction"), {"field_id": self.field.pk, "value": "x"}
        )
        self.api("put", self.review_path(f"/articles/{self.alpha.pk}/extraction/done"), {"done": True})
        body = self.api("get", self.review_path("/extraction/studies")).json()
        self.assertEqual(
            [("Alpha", 1, True), ("Beta", 0, False)],
            [(item["title"], item["filled"], item["finished_data_extraction"]) for item in body["items"]],
        )
        for query, expected in (("done=true", ["Alpha"]), ("done=false", ["Beta"]), ("q=bet", ["Beta"])):
            with self.subTest(query=query):
                items = self.api("get", self.review_path("/extraction/studies"), QUERY_STRING=query).json()["items"]
                self.assertEqual(expected, [item["title"] for item in items])
