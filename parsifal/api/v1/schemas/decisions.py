from datetime import datetime
from typing import Any

from ninja import Schema

from parsifal.api.v1.schemas.articles import ArticleOut


class DecisionOut(Schema):
    id: int
    article_id: int
    user: str
    stage: str
    status: str
    selection_criteria_id: int | None = None
    comments: str
    decided_at: datetime

    @staticmethod
    def resolve_user(obj):
        return obj.user.username


class DecisionIn(Schema):
    ids: list[int]
    status: str
    stage: str = "title_abstract"
    selection_criteria_id: int | None = None
    comments: str = ""


class AgreementOut(Schema):
    stage: str
    user_a: str
    user_b: str
    compared: int
    agreed: int
    percent_agreement: float | None = None
    kappa: float | None = None
    interpretation: str
    reviewers: list[str]


class DisagreementOut(Schema):
    article: ArticleOut
    decisions: list[DecisionOut]


class ConsolidateIn(Schema):
    stage: str = "title_abstract"
    rule: str = "unanimous"
    ids: list[int] | None = None


class ConsolidateOut(Schema):
    stage: str
    rule: str
    resolved: int  # articles the rule decided (their status was set)
    unresolved: int  # articles it could not decide (status untouched)
    changed: int  # resolved articles whose status was different before
    resolved_ids: list[int]
    unresolved_ids: list[int]
    changed_ids: list[int]


class DecisionSummaryOut(Schema):
    stage: str
    reviewers: dict[str, Any]
    articles: int
