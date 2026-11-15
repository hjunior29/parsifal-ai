"""Quality assessment: checklist (questions, weighted answers, cut-off) and per-article assessments."""

from django.db.models import Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce

from parsifal.apps.core.exceptions import Conflict, ValidationError
from parsifal.apps.reviews.models import QualityAnswer, QualityAssessment, QualityQuestion, ReviewEvent
from parsifal.apps.reviews.services import history, reviews
from parsifal.apps.reviews.services._common import check_length, get_child, reorder, require

# What the History records of the quality assessment checklist (the web views of Planning record the same).
QUESTION = history.Kind("quality assessment question", ReviewEvent.PLANNING, ("description",))
ANSWER = history.Kind("quality assessment answer", ReviewEvent.PLANNING, ("description", "weight"))


def record_suggested_answers(review, answers):
    history.record(
        review,
        ReviewEvent.PLANNING,
        history.ADDED,
        "Added the suggested quality assessment answers",
        subject=ANSWER.subject,
        items=[f"{answer.description} ({history.show(answer.weight)})" for answer in answers],
    )


def add_question(*, review, description):
    require(description, field="description")
    check_length(description, 255, field="description")
    order = review.qualityquestion_set.count()
    question = QualityQuestion.objects.create(review=review, description=description, order=order)
    QUESTION.added(review, question)
    return question


def update_question(*, review, question_id, description):
    question = get_child(review.qualityquestion_set, question_id, label="Quality question")
    require(description, field="description")
    tracker = QUESTION.track(question)
    question.description = check_length(description, 255, field="description")
    question.save(update_fields=["description"])
    QUESTION.changed(review, tracker)
    return question


def remove_question(*, review, question_id):
    question = get_child(review.qualityquestion_set, question_id, label="Quality question")
    QUESTION.removed(review, question)
    question.delete()


def reorder_questions(*, review, ordered_ids):
    before = QUESTION.order(review.qualityquestion_set)
    questions = reorder(review.qualityquestion_set, ordered_ids, label="Quality question")
    QUESTION.reordered(review, review.qualityquestion_set, before)
    return questions


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
    answer = QualityAnswer.objects.create(review=review, description=description, weight=_parse_weight(weight))
    ANSWER.added(review, answer)
    return answer


def update_answer(*, review, answer_id, description=None, weight=None):
    answer = get_child(review.qualityanswer_set, answer_id, label="Quality answer")
    tracker = ANSWER.track(answer)
    if description is not None:
        require(description, field="description")
        answer.description = check_length(description, 255, field="description")
    if weight is not None:
        answer.weight = _parse_weight(weight)
    answer.save()
    ANSWER.changed(review, tracker)
    return answer


def remove_answer(*, review, answer_id):
    answer = get_child(review.qualityanswer_set, answer_id, label="Quality answer")
    ANSWER.removed(review, answer)
    answer.delete()


def add_suggested_answers(*, review):
    """Yes / Partially / No with weights 1.0 / 0.5 / 0.0; only when the review has no answers yet."""
    if review.qualityanswer_set.exists():
        raise Conflict("This review already has quality assessment answers.")
    answers = [
        QualityAnswer.objects.create(review=review, description=description, weight=weight)
        for description, weight in QualityAnswer.SUGGESTED_ANSWERS
    ]
    record_suggested_answers(review, answers)
    return answers


def max_score(review):
    return review.calculate_quality_assessment_max_score()


def set_cutoff(*, review, cutoff):
    try:
        cutoff = float(cutoff)
    except (TypeError, ValueError):
        raise ValidationError("cutoff must be a number.", field="cutoff")
    if cutoff < 0:
        raise ValidationError("cutoff cannot be negative.", field="cutoff")
    tracker = reviews.track_review(review, "quality_assessment_cutoff_score")
    review.quality_assessment_cutoff_score = cutoff
    review.save(update_fields=["quality_assessment_cutoff_score", "last_update"])
    reviews.record_changes(review, tracker)
    return review


def assess(*, review, article_id, question_id, answer_id, actor=None):
    """
    Record (or replace) the answer to one checklist question for one article; without an answer (``None``), clear it:
    the question goes back to unanswered (returns None).
    """
    article = get_child(review.article_set, article_id, label="Article")
    question = get_child(review.qualityquestion_set, question_id, label="Quality question")
    before = QualityAssessment.objects.filter(article=article, question=question).select_related("answer").first()
    before = before.answer.description if before and before.answer else ""
    if answer_id is None:
        QualityAssessment.objects.filter(article=article, question=question).delete()
        _record_answer(review, article, question, before, "", actor)
        return None
    answer = get_child(review.qualityanswer_set, answer_id, label="Quality answer")
    assessment, _created = QualityAssessment.objects.update_or_create(
        article=article, question=question, defaults={"answer": answer, "user": actor}
    )
    _record_answer(review, article, question, before, answer.description, actor)
    return assessment


def _record_answer(review, article, question, before, after, actor):
    if before == after:
        return
    verb = "Answered" if after else "Cleared the answer to"
    history.record(
        review,
        ReviewEvent.QUALITY,
        history.CHANGED,
        f"{verb} {history.quote(question.description)} for the study {history.quote(article.title)}",
        subject="quality_assessment",
        changes=[history.change(question.description, before, after, "answer")],
        articles=[article],
        actor=actor,
    )


def article_assessments(*, review, article_id):
    article = get_child(review.article_set, article_id, label="Article")
    return article.qualityassessment_set.select_related("question", "answer").order_by("question__order")


def article_score(*, review, article_id):
    article = get_child(review.article_set, article_id, label="Article")
    return article.get_score()


# The orders of the studies to assess (a leading "-" reverses one); studies without a year go last either way.
ORDERS = {"title": F("title"), "year": F("year_int")}
# What the list of studies to assess may be limited to.
STATES = ("done", "pending", "above", "below")


def assessment_list(review, *, query=None, state=None, order=None):
    """
    The accepted studies to assess, with their score (``score``) and how many questions each has an answer to
    (``answered``): only those whose title has ``query``, and in ``state``, if any — done (every question answered),
    pending (not yet), above (score above the cutoff) or below (at most the cutoff); in ``order``: title (default) or
    year, a leading "-" reverses it.
    """
    order = (order or "title").strip()
    key = order.lstrip("-")
    if key not in ORDERS or order.count("-") > 1:
        raise ValidationError("order must be title, -title, year or -year.", field="order")
    value = ORDERS[key].desc(nulls_last=True) if order.startswith("-") else ORDERS[key].asc(nulls_last=True)
    articles = (
        review.get_accepted_articles()
        .annotate(
            score=Coalesce(Sum("qualityassessment__answer__weight"), Value(0.0)),
            answered=Count("qualityassessment", filter=Q(qualityassessment__answer__isnull=False)),
        )
        .order_by(value, "title", "pk")
    )
    if query and query.strip():
        articles = articles.filter(title__icontains=query.strip())
    if state:
        if state not in STATES:
            raise ValidationError(f"state must be one of {', '.join(STATES)}.", field="state")
        questions = review.qualityquestion_set.count()
        cutoff = review.quality_assessment_cutoff_score
        articles = articles.filter(
            {
                "done": Q(answered__gte=questions),
                "pending": Q(answered__lt=questions),
                "above": Q(score__gt=cutoff),
                "below": Q(score__lte=cutoff),
            }[state]
        )
    return articles


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
