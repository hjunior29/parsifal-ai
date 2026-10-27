"""Quality assessment: checklist (questions, weighted answers, cut-off) and per-article assessments."""

from django.db.models import Sum, Value
from django.db.models.functions import Coalesce

from parsifal.apps.core.exceptions import Conflict, ValidationError
from parsifal.apps.reviews.models import QualityAnswer, QualityAssessment, QualityQuestion
from parsifal.apps.reviews.services._common import check_length, get_child, reorder, require


def add_question(*, review, description):
    require(description, field="description")
    check_length(description, 255, field="description")
    order = review.qualityquestion_set.count()
    return QualityQuestion.objects.create(review=review, description=description, order=order)


def update_question(*, review, question_id, description):
    question = get_child(review.qualityquestion_set, question_id, label="Quality question")
    require(description, field="description")
    question.description = check_length(description, 255, field="description")
    question.save(update_fields=["description"])
    return question


def remove_question(*, review, question_id):
    get_child(review.qualityquestion_set, question_id, label="Quality question").delete()


def reorder_questions(*, review, ordered_ids):
    return reorder(review.qualityquestion_set, ordered_ids, label="Quality question")


def _parse_weight(weight):
    if isinstance(weight, str):
        weight = weight.replace(",", ".")
    try:
        return float(weight)
    except (TypeError, ValueError):
        raise ValidationError("weight must be a number.", field="weight")


def add_answer(*, review, description, weight):
    require(description, field="description")
    check_length(description, 255, field="description")
    return QualityAnswer.objects.create(review=review, description=description, weight=_parse_weight(weight))


def update_answer(*, review, answer_id, description=None, weight=None):
    answer = get_child(review.qualityanswer_set, answer_id, label="Quality answer")
    if description is not None:
        require(description, field="description")
        answer.description = check_length(description, 255, field="description")
    if weight is not None:
        answer.weight = _parse_weight(weight)
    answer.save()
    return answer


def remove_answer(*, review, answer_id):
    get_child(review.qualityanswer_set, answer_id, label="Quality answer").delete()


def add_suggested_answers(*, review):
    """Yes / Partially / No with weights 1.0 / 0.5 / 0.0; only when the review has no answers yet."""
    if review.qualityanswer_set.exists():
        raise Conflict("This review already has quality assessment answers.")
    return [
        QualityAnswer.objects.create(review=review, description=description, weight=weight)
        for description, weight in QualityAnswer.SUGGESTED_ANSWERS
    ]


def max_score(review):
    return review.calculate_quality_assessment_max_score()


def set_cutoff(*, review, cutoff):
    try:
        cutoff = float(cutoff)
    except (TypeError, ValueError):
        raise ValidationError("cutoff must be a number.", field="cutoff")
    if cutoff < 0:
        raise ValidationError("cutoff cannot be negative.", field="cutoff")
    review.quality_assessment_cutoff_score = cutoff
    review.save(update_fields=["quality_assessment_cutoff_score", "last_update"])
    return review


def assess(*, review, article_id, question_id, answer_id, actor=None):
    """
    Record (or replace) the answer to one checklist question for one article; without an answer (``None``), clear it:
    the question goes back to unanswered (returns None).
    """
    article = get_child(review.article_set, article_id, label="Article")
    question = get_child(review.qualityquestion_set, question_id, label="Quality question")
    if answer_id is None:
        QualityAssessment.objects.filter(article=article, question=question).delete()
        return None
    answer = get_child(review.qualityanswer_set, answer_id, label="Quality answer")
    assessment, _created = QualityAssessment.objects.update_or_create(
        article=article, question=question, defaults={"answer": answer, "user": actor}
    )
    return assessment


def article_assessments(*, review, article_id):
    article = get_child(review.article_set, article_id, label="Article")
    return article.qualityassessment_set.select_related("question", "answer").order_by("question__order")


def article_score(*, review, article_id):
    article = get_child(review.article_set, article_id, label="Article")
    return article.get_score()


def summary(review):
    """Accepted articles with their score and whether they pass the cut-off."""
    cutoff = review.quality_assessment_cutoff_score
    has_checklist = review.has_quality_assessment_checklist()
    rows = []
    articles = review.get_accepted_articles().annotate(
        score=Coalesce(Sum("qualityassessment__answer__weight"), Value(0.0))
    )
    for article in articles.order_by("title"):
        rows.append(
            {
                "article_id": article.pk,
                "title": article.title,
                "year": article.year,
                "score": article.score,
                "passes_cutoff": (not has_checklist) or cutoff <= 0 or article.score > cutoff,
            }
        )
    return {"max_score": max_score(review), "cutoff": cutoff, "has_checklist": has_checklist, "articles": rows}
