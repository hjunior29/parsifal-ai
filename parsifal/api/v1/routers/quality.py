from ninja import Router

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.common import OrderIn
from parsifal.api.v1.schemas.quality import (
    ArticleQualityOut,
    AssessmentIn,
    CutoffIn,
    MaxScoreOut,
    QualityAnswerIn,
    QualityAnswerOut,
    QualityAnswerUpdateIn,
    QualityQuestionIn,
    QualityQuestionOut,
    QualitySummaryOut,
)
from parsifal.apps.reviews.services import quality

router = Router(tags=["quality"])


@router.get(
    "/reviews/{int:review_id}/quality/questions",
    response=list[QualityQuestionOut],
    operation_id="quality_questions_list",
)
def quality_questions_list(request, review_id: int):
    return get_review(request, review_id).qualityquestion_set.all()


@router.post(
    "/reviews/{int:review_id}/quality/questions",
    response={201: QualityQuestionOut},
    operation_id="quality_questions_create",
)
def quality_questions_create(request, review_id: int, payload: QualityQuestionIn):
    return 201, quality.add_question(review=get_review(request, review_id), description=payload.description)


@router.patch(
    "/reviews/{int:review_id}/quality/questions/{int:question_id}",
    response=QualityQuestionOut,
    operation_id="quality_questions_update",
)
def quality_questions_update(request, review_id: int, question_id: int, payload: QualityQuestionIn):
    review = get_review(request, review_id)
    return quality.update_question(review=review, question_id=question_id, description=payload.description)


@router.delete(
    "/reviews/{int:review_id}/quality/questions/{int:question_id}",
    response={204: None},
    operation_id="quality_questions_delete",
)
def quality_questions_delete(request, review_id: int, question_id: int):
    quality.remove_question(review=get_review(request, review_id), question_id=question_id)
    return 204, None


@router.put(
    "/reviews/{int:review_id}/quality/questions/order",
    response=list[QualityQuestionOut],
    operation_id="quality_questions_reorder",
)
def quality_questions_reorder(request, review_id: int, payload: OrderIn):
    return quality.reorder_questions(review=get_review(request, review_id), ordered_ids=payload.ids)


@router.get(
    "/reviews/{int:review_id}/quality/answers", response=list[QualityAnswerOut], operation_id="quality_answers_list"
)
def quality_answers_list(request, review_id: int):
    return get_review(request, review_id).qualityanswer_set.all()


@router.post(
    "/reviews/{int:review_id}/quality/answers", response={201: QualityAnswerOut}, operation_id="quality_answers_create"
)
def quality_answers_create(request, review_id: int, payload: QualityAnswerIn):
    review = get_review(request, review_id)
    return 201, quality.add_answer(review=review, description=payload.description, weight=payload.weight)


@router.post(
    "/reviews/{int:review_id}/quality/answers/suggested",
    response={201: list[QualityAnswerOut]},
    operation_id="quality_answers_suggested",
)
def quality_answers_suggested(request, review_id: int):
    """Create the Yes (1.0) / Partially (0.5) / No (0.0) answers; fails if the review already has answers."""
    return 201, quality.add_suggested_answers(review=get_review(request, review_id))


@router.patch(
    "/reviews/{int:review_id}/quality/answers/{int:answer_id}",
    response=QualityAnswerOut,
    operation_id="quality_answers_update",
)
def quality_answers_update(request, review_id: int, answer_id: int, payload: QualityAnswerUpdateIn):
    review = get_review(request, review_id)
    return quality.update_answer(review=review, answer_id=answer_id, **payload.dict(exclude_unset=True))


@router.delete(
    "/reviews/{int:review_id}/quality/answers/{int:answer_id}",
    response={204: None},
    operation_id="quality_answers_delete",
)
def quality_answers_delete(request, review_id: int, answer_id: int):
    quality.remove_answer(review=get_review(request, review_id), answer_id=answer_id)
    return 204, None


@router.get("/reviews/{int:review_id}/quality/max-score", response=MaxScoreOut, operation_id="quality_max_score")
def quality_max_score(request, review_id: int):
    return MaxScoreOut(max_score=quality.max_score(get_review(request, review_id)))


@router.put("/reviews/{int:review_id}/quality/cutoff", response=MaxScoreOut, operation_id="quality_set_cutoff")
def quality_set_cutoff(request, review_id: int, payload: CutoffIn):
    review = quality.set_cutoff(review=get_review(request, review_id), cutoff=payload.cutoff)
    return MaxScoreOut(max_score=review.quality_assessment_cutoff_score)


@router.get("/reviews/{int:review_id}/quality/summary", response=QualitySummaryOut, operation_id="quality_summary")
def quality_summary(request, review_id: int):
    return quality.summary(get_review(request, review_id))


def _article_quality(review, article_id):
    return ArticleQualityOut(
        article_id=article_id,
        score=quality.article_score(review=review, article_id=article_id),
        assessments=list(quality.article_assessments(review=review, article_id=article_id)),
    )


@router.get(
    "/reviews/{int:review_id}/articles/{int:article_id}/quality",
    response=ArticleQualityOut,
    operation_id="article_quality_get",
)
def article_quality_get(request, review_id: int, article_id: int):
    return _article_quality(get_review(request, review_id), article_id)


@router.put(
    "/reviews/{int:review_id}/articles/{int:article_id}/quality",
    response=ArticleQualityOut,
    operation_id="article_quality_assess",
)
def article_quality_assess(request, review_id: int, article_id: int, payload: AssessmentIn):
    """Answer one checklist question for the article (replaces a previous answer to the same question)."""
    review = get_review(request, review_id)
    quality.assess(
        review=review,
        article_id=article_id,
        question_id=payload.question_id,
        answer_id=payload.answer_id,
        actor=request.auth,
    )
    return _article_quality(review, article_id)
