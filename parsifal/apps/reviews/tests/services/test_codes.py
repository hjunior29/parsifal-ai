from django.test import TestCase

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import Question, ReviewEvent, SelectionCriteria
from parsifal.apps.reviews.services import codes, protocol, reviews
from parsifal.apps.reviews.tests.factories import (
    DataExtractionFieldFactory,
    QualityQuestionFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
)


class TestCodes(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory()

    def test_from_the_order_without_a_leading_zero(self):
        first = Question.objects.create(review=self.review, question="What exists?", order=1)
        second = Question.objects.create(review=self.review, question="Where?", order=0)
        Question.objects.create(review=self.review, question="Which ones?", order=0, parent_question=first)
        Question.objects.create(review=self.review, question="How many?", order=1, parent_question=first)
        self.assertEqual(
            [("Where?", "RQ1"), ("Which ones?", "RQ2.1"), ("What exists?", "RQ2"), ("How many?", "RQ2.2")],
            [(item.question, item.code) for item in codes.questions(self.review)],
        )
        protocol.reorder_questions(review=self.review, ordered_ids=[first.pk, second.pk])
        self.assertEqual("RQ1", codes.code_of(self.review, Question.objects.get(pk=first.pk)).code)
        for index in range(12):
            DataExtractionFieldFactory(review=self.review, description=f"Field {index}", order=index)
        self.assertEqual(["EX1", "EX2"], [field.code for field in codes.fields(self.review)][:2])
        self.assertEqual("EX12", codes.fields(self.review)[-1].code)

    def test_criteria_by_type_and_their_order(self):
        tool = protocol.add_criteria(review=self.review, description="Proposes a tool", criteria_type="I")
        english = protocol.add_criteria(review=self.review, description="Not in English", criteria_type="E")
        primary = protocol.add_criteria(review=self.review, description="Not a primary study", criteria_type="E")
        self.assertEqual(
            [("Proposes a tool", "IC1"), ("Not in English", "EC1"), ("Not a primary study", "EC2")],
            [(item.description, item.code) for item in codes.criteria(self.review)],
        )
        protocol.reorder_criteria(review=self.review, ordered_ids=[primary.pk, english.pk])
        self.assertEqual(
            ["Not a primary study", "Not in English"],
            [item.description for item in codes.criteria(self.review, SelectionCriteria.EXCLUSION)],
        )
        self.assertEqual("Reordered the exclusion criteria", self.review.events.order_by("pk").last().summary)
        with self.assertRaises(ValidationError):
            protocol.reorder_criteria(review=self.review, ordered_ids=[tool.pk, english.pk])
        QualityQuestionFactory(review=self.review, description="Clear?")
        self.assertEqual(["QA1"], [item.code for item in codes.quality_questions(self.review)])

    def test_the_prefixes_of_the_review(self):
        reviews.update_review(review=self.review, code_prefixes=["question=QP", "inclusion=CI", "exclusion=CE"])
        self.review.refresh_from_db()
        self.assertEqual(
            {"question": "QP", "inclusion": "CI", "exclusion": "CE", "quality": "QA", "extraction": "EX"},
            codes.prefixes(self.review),
        )
        SelectionCriteriaFactory(review=self.review, criteria_type="E", description="Off topic")
        self.assertEqual(["CE1"], [item.code for item in codes.criteria(self.review)])
        event = self.review.events.order_by("pk").last()
        self.assertEqual((ReviewEvent.REVIEW, False), (event.area, event.amendment))
        for value in (["question"], ["kind=XX"], {"question": "1Q"}, {"question": "QUESTIONS"}, {"inclusion": "CE"}):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    reviews.update_review(review=self.review, code_prefixes=value)

    def test_the_codes_written_by_hand(self):
        Question.objects.create(review=self.review, question="RQ1: What applications exist?", order=0)
        sub = Question.objects.create(review=self.review, question="RQ1.1: Do authors share code?", order=1)
        QualityQuestionFactory(review=self.review, description="QL1 | Is the problem clear?")
        field = DataExtractionFieldFactory(review=self.review, description="EX01 | Problem addressed: the need.")
        DataExtractionFieldFactory(review=self.review, description="COVID-19: impact", order=1)  # not a code
        DataExtractionFieldFactory(review=self.review, description="AI-based tools", order=2)
        SelectionCriteriaFactory(review=self.review, criteria_type="E", description="EC2 - Not in English")
        rows = codes.written(self.review)
        self.assertEqual(
            [
                ("question", "RQ1", "What applications exist?"),
                ("question", "RQ1.1", "Do authors share code?"),
                ("criteria", "EC2", "Not in English"),
                ("quality", "QL1", "Is the problem clear?"),
                ("extraction", "EX01", "Problem addressed: the need."),
            ],
            [(row["kind"], row["written"], row["after"]) for row in rows],
        )
        changed = codes.strip_written(review=self.review, keys=[f"question-{sub.pk}", f"extraction-{field.pk}"])
        self.assertEqual(2, len(changed))
        sub.refresh_from_db()
        field.refresh_from_db()
        self.assertEqual(("Do authors share code?", "Problem addressed: the need."), (sub.question, field.description))
        event = self.review.events.order_by("pk").last()
        self.assertEqual(
            ("Removed the codes written in 2 names (the review numbers them now)", ReviewEvent.REVIEW),
            (event.summary, event.area),
        )
        self.assertIn("RQ1.1: Do authors share code? → Do authors share code?", event.items)
        with self.assertRaises(ValidationError):
            codes.strip_written(review=self.review, keys=["question-999999"])
        self.assertEqual(3, len(codes.strip_written(review=self.review)))
        self.assertEqual([], codes.written(self.review))
