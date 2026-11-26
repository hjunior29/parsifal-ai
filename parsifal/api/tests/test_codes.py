from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.reviews.models import Question
from parsifal.apps.reviews.tests.factories import (
    DataExtractionFieldFactory,
    QualityQuestionFactory,
    SelectionCriteriaFactory,
)


class TestCodesApi(ApiTestCase):
    def test_every_list_has_its_codes(self):
        main = Question.objects.create(review=self.review, question="RQ1: What exists?", order=0)
        Question.objects.create(review=self.review, question="Which ones?", order=1, parent_question=main)
        first = SelectionCriteriaFactory(review=self.review, criteria_type="E", description="Not in English")
        second = SelectionCriteriaFactory(review=self.review, criteria_type="E", description="Not primary", order=1)
        QualityQuestionFactory(review=self.review, description="Clear?")
        DataExtractionFieldFactory(review=self.review, description="Country")
        self.assertEqual(["RQ1", "RQ1.1"], [q["code"] for q in self.api("get", self.review_path("/questions")).json()])
        self.assertEqual(["QA1"], [q["code"] for q in self.api("get", self.review_path("/quality/questions")).json()])
        self.assertEqual(["EX1"], [f["code"] for f in self.api("get", self.review_path("/extraction/fields")).json()])
        body = self.api("put", self.review_path("/criteria/order"), {"ids": [second.pk, first.pk]}).json()
        self.assertEqual(
            [("EC1", "Not primary"), ("EC2", "Not in English")], [(c["code"], c["description"]) for c in body]
        )
        created = self.api(
            "post", self.review_path("/criteria"), {"description": "A tool", "criteria_type": "I"}
        ).json()
        self.assertEqual("IC1", created["code"])

    def test_prefixes_and_the_codes_written_by_hand(self):
        body = self.api(
            "patch", self.review_path(), {"code_prefixes": ["question=QP", "inclusion=CI", "exclusion=CE"]}
        ).json()
        self.assertEqual("QP", body["code_prefixes"]["question"])
        self.assertEqual(422, self.api("patch", self.review_path(), {"code_prefixes": {"question": "CE"}}).status_code)
        question = Question.objects.create(review=self.review, question="QP1: What exists?", order=0)
        codes = self.api("get", self.review_path("/codes")).json()
        self.assertEqual("CE", codes["prefixes"]["exclusion"])
        self.assertEqual(
            [
                {
                    "key": f"question-{question.pk}",
                    "kind": "question",
                    "id": question.pk,
                    "code": "QP1",
                    "written": "QP1",
                    "before": "QP1: What exists?",
                    "after": "What exists?",
                }
            ],
            codes["written"],
        )
        stripped = self.api("post", self.review_path("/codes/strip"), {}).json()
        self.assertEqual(["What exists?"], [row["after"] for row in stripped])
        question.refresh_from_db()
        self.assertEqual("What exists?", question.question)
        self.assertEqual(422, self.api("post", self.review_path("/codes/strip"), {"keys": ["question-0"]}).status_code)
