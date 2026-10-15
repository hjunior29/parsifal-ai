from django.test import TestCase

from parsifal.apps.core.exceptions import Conflict, NotFound, ValidationError
from parsifal.apps.reviews.models import QualityAssessment
from parsifal.apps.reviews.services import quality
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    QualityAnswerFactory,
    QualityQuestionFactory,
    ReviewFactory,
    SourceFactory,
)


class TestChecklist(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory()

    def test_questions_crud_and_reorder(self):
        q1 = quality.add_question(review=self.review, description="Is the method described?")
        q2 = quality.add_question(review=self.review, description="Are threats discussed?")
        quality.update_question(review=self.review, question_id=q1.pk, description="Is the method clear?")
        quality.reorder_questions(review=self.review, ordered_ids=[q2.pk, q1.pk])
        self.assertEqual(
            ["Are threats discussed?", "Is the method clear?"],
            list(self.review.qualityquestion_set.order_by("order").values_list("description", flat=True)),
        )
        quality.remove_question(review=self.review, question_id=q1.pk)
        self.assertEqual(1, self.review.qualityquestion_set.count())

    def test_answers_and_weights(self):
        answer = quality.add_answer(review=self.review, description="Yes", weight="1,0")
        self.assertEqual(1.0, answer.weight)
        quality.update_answer(review=self.review, answer_id=answer.pk, weight=0.75)
        answer.refresh_from_db()
        self.assertEqual(0.75, answer.weight)
        with self.assertRaises(ValidationError):
            quality.add_answer(review=self.review, description="Bad", weight="heavy")

    def test_suggested_answers_only_once(self):
        answers = quality.add_suggested_answers(review=self.review)
        self.assertEqual([("Yes", 1.0), ("Partially", 0.5), ("No", 0.0)], [(a.description, a.weight) for a in answers])
        with self.assertRaises(Conflict):
            quality.add_suggested_answers(review=self.review)

    def test_max_score_and_cutoff(self):
        QualityQuestionFactory.create_batch(3, review=self.review)
        QualityAnswerFactory(review=self.review, weight=1.0)
        QualityAnswerFactory(review=self.review, weight=0.5)
        self.assertEqual(3.0, quality.max_score(self.review))
        quality.set_cutoff(review=self.review, cutoff="1.5")
        self.review.refresh_from_db()
        self.assertEqual(1.5, self.review.quality_assessment_cutoff_score)
        with self.assertRaises(ValidationError):
            quality.set_cutoff(review=self.review, cutoff=-1)

    def test_scoping(self):
        foreign = QualityQuestionFactory()
        with self.assertRaises(NotFound):
            quality.remove_question(review=self.review, question_id=foreign.pk)


class TestAssessments(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source])
        cls.actor = cls.review.author
        cls.q1 = QualityQuestionFactory(review=cls.review)
        cls.q2 = QualityQuestionFactory(review=cls.review)
        cls.yes = QualityAnswerFactory(review=cls.review, description="Yes", weight=1.0)
        cls.partially = QualityAnswerFactory(review=cls.review, description="Partially", weight=0.5)
        cls.article = ArticleFactory(review=cls.review, source=cls.source, status="A")

    def test_assess_replaces_and_scores(self):
        quality.assess(
            review=self.review,
            article_id=self.article.pk,
            question_id=self.q1.pk,
            answer_id=self.yes.pk,
            actor=self.actor,
        )
        quality.assess(
            review=self.review,
            article_id=self.article.pk,
            question_id=self.q1.pk,
            answer_id=self.partially.pk,
            actor=self.actor,
        )
        quality.assess(review=self.review, article_id=self.article.pk, question_id=self.q2.pk, answer_id=self.yes.pk)
        with self.subTest(msg="one row per question"):
            self.assertEqual(2, QualityAssessment.objects.filter(article=self.article).count())
        with self.subTest(msg="score is the sum of weights"):
            self.assertEqual(1.5, quality.article_score(review=self.review, article_id=self.article.pk))
        with self.subTest(msg="actor recorded"):
            self.assertEqual(self.actor, QualityAssessment.objects.get(article=self.article, question=self.q1).user)

    def test_assess_scoping(self):
        foreign_question = QualityQuestionFactory()
        with self.assertRaises(NotFound):
            quality.assess(
                review=self.review, article_id=self.article.pk, question_id=foreign_question.pk, answer_id=self.yes.pk
            )
        foreign_article = ArticleFactory()
        with self.assertRaises(NotFound):
            quality.assess(
                review=self.review, article_id=foreign_article.pk, question_id=self.q1.pk, answer_id=self.yes.pk
            )

    def test_summary_and_cutoff(self):
        other = ArticleFactory(review=self.review, source=self.source, status="A", title="Weak")
        quality.assess(review=self.review, article_id=self.article.pk, question_id=self.q1.pk, answer_id=self.yes.pk)
        quality.assess(review=self.review, article_id=self.article.pk, question_id=self.q2.pk, answer_id=self.yes.pk)
        quality.assess(review=self.review, article_id=other.pk, question_id=self.q1.pk, answer_id=self.partially.pk)
        quality.set_cutoff(review=self.review, cutoff=1.0)
        summary = quality.summary(self.review)
        by_id = {row["article_id"]: row for row in summary["articles"]}
        self.assertEqual((2.0, True), (by_id[self.article.pk]["score"], by_id[self.article.pk]["passes_cutoff"]))
        self.assertEqual((0.5, False), (by_id[other.pk]["score"], by_id[other.pk]["passes_cutoff"]))
        self.assertEqual(2.0, summary["max_score"])
        with self.subTest(msg="final selection follows the cutoff"):
            self.assertEqual([self.article.pk], [a.pk for a in self.review.get_final_selection_articles()])
