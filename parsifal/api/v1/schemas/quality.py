from typing import Any

from ninja import Schema


class QualityQuestionOut(Schema):
    id: int
    description: str
    order: int


class QualityQuestionIn(Schema):
    description: str


class QualityAnswerOut(Schema):
    id: int
    description: str
    weight: float


class QualityAnswerIn(Schema):
    description: str
    weight: float


class QualityAnswerUpdateIn(Schema):
    description: str | None = None
    weight: float | None = None


class CutoffIn(Schema):
    cutoff: float


class MaxScoreOut(Schema):
    max_score: float


class AssessmentIn(Schema):
    question_id: int
    answer_id: int | None = None


class AssessmentOut(Schema):
    question_id: int
    answer_id: int | None = None
    user: str | None = None

    @staticmethod
    def resolve_user(obj):
        return obj.user.username if obj.user else None


class ArticleQualityOut(Schema):
    article_id: int
    score: float
    assessments: list[AssessmentOut]


class QualitySummaryOut(Schema):
    max_score: float
    cutoff: float
    has_checklist: bool
    articles: list[dict[str, Any]]


class QualityStudyOut(Schema):
    """A study of Quality Assessment's list."""

    article_id: int
    title: str
    year: str | None = None
    score: float  # the sum of its answers' weights
    answered: int  # questions with an answer

    @staticmethod
    def resolve_article_id(obj):
        return obj.pk
