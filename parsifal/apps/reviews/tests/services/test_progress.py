from django.core.files.base import ContentFile
from django.test import TestCase

from parsifal.apps.core.tests.files import PDF, TemporaryFilesMixin
from parsifal.apps.reviews.models import Article, Review
from parsifal.apps.reviews.services import extraction, manuscripts, progress, protocol, quality, threats
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    DataExtractionFieldFactory,
    QualityAnswerFactory,
    QualityQuestionFactory,
    ReviewFactory,
    SourceFactory,
)


def steps(review):
    return {step["key"]: step["done"] for phase in progress.progress(review)["phases"] for step in phase["steps"]}


class TestProgress(TemporaryFilesMixin, TestCase):
    def test_a_new_review(self):
        result = progress.progress(ReviewFactory(objective=""))
        self.assertEqual(0, result["percent"])
        self.assertEqual("objective", result["next"]["key"])
        self.assertEqual(
            [("planning", 20), ("conducting", 70), ("reporting", 10)],
            [(p["key"], p["weight"]) for p in result["phases"]],
        )

    def test_one_field_of_the_picoc_is_enough(self):
        review = ReviewFactory(population="", intervention="smart glasses", comparison="", outcome="", context="")
        self.assertEqual(1.0, steps(review)["picoc"])
        review.intervention = ""
        self.assertEqual(0.0, steps(review)["picoc"])

    def test_quality_assessment_is_a_step_of_an_slr_only(self):
        self.assertIn("quality", steps(ReviewFactory(review_type=Review.SLR)))
        mapping = ReviewFactory(review_type=Review.MAPPING)
        self.assertNotIn("quality", steps(mapping))
        self.assertNotIn("quality_checklist", steps(mapping))
        QualityQuestionFactory(review=mapping)
        QualityAnswerFactory(review=mapping)
        self.assertIn("quality", steps(mapping))  # it has a checklist: it counts

    def test_the_studies_count_in_proportion(self):
        review = ReviewFactory(review_type=Review.SLR)
        source = SourceFactory()
        question = QualityQuestionFactory(review=review)
        yes = QualityAnswerFactory(review=review)
        field = DataExtractionFieldFactory(review=review)
        accepted = [ArticleFactory(review=review, source=source, status=Article.ACCEPTED) for _ in range(2)]
        ArticleFactory(review=review, source=source, status=Article.REJECTED)
        ArticleFactory(review=review, source=source, status=Article.UNCLASSIFIED)
        ArticleFactory(review=review, source=source, status=Article.DUPLICATED)  # left out
        quality.assess(review=review, article_id=accepted[0].pk, question_id=question.pk, answer_id=yes.pk)
        extraction.set_value(review=review, article_id=accepted[0].pk, field_id=field.pk, value="x", evidence="p. 1")
        extraction.mark_done(review=review, article_id=accepted[0].pk)
        done = steps(review)
        self.assertEqual(
            (1.0, 0.75, 0.5, 0.5), (done["studies"], done["selection"], done["quality"], done["extraction"])
        )

    def test_complete_only_with_everything_and_a_manuscript(self):
        source = SourceFactory()
        review = ReviewFactory(review_type=Review.MAPPING, objective="Why", population="engineers", sources=[source])
        protocol.add_question(review=review, description="RQ1")
        protocol.set_generic_search_string(review=review, search_string="a AND b")
        protocol.add_criteria(review=review, description="Not in English", criteria_type="E")
        field = DataExtractionFieldFactory(review=review)
        study = ArticleFactory(review=review, source=source, status=Article.ACCEPTED)
        extraction.set_value(review=review, article_id=study.pk, field_id=field.pk, value="x", evidence="p. 1")
        extraction.mark_done(review=review, article_id=study.pk)
        threats.add_threat(review=review, title="One reviewer")
        result = progress.progress(review)
        self.assertEqual(("manuscript", 95), (result["next"]["key"], result["percent"]))  # all but half of Reporting
        paper = manuscripts.add_manuscript(review=review, name="Full paper")
        self.assertEqual(95, progress.progress(review)["percent"])  # no version yet
        manuscripts.add_version(review=review, manuscript_id=paper.pk, file=ContentFile(PDF, name="paper.pdf"))
        result = progress.progress(review)
        self.assertEqual((100, None), (result["percent"], result["next"]))
