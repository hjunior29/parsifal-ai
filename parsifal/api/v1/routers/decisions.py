"""Per-reviewer screening decisions, agreement and consolidation (Kitchenham 6.2.3, Petersen 5.1.2)."""

from ninja import Router

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.decisions import (
    AgreementOut,
    ConsolidateIn,
    ConsolidateOut,
    DecisionIn,
    DecisionOut,
    DecisionSummaryOut,
    DisagreementOut,
)
from parsifal.apps.reviews.services import decisions

router = Router(tags=["decisions"])


@router.get("/reviews/{int:review_id}/decisions", response=list[DecisionOut], operation_id="decisions_list")
def decisions_list(
    request,
    review_id: int,
    stage: str | None = None,
    user_id: int | None = None,
    article_id: int | None = None,
    status: str | None = None,
):
    """Individual decisions; filter by stage (title_abstract | full_text), reviewer, article or status."""
    review = get_review(request, review_id)
    return decisions.list_decisions(review, stage=stage, user_id=user_id, article_id=article_id, status=status)


@router.post("/reviews/{int:review_id}/decisions", response=list[DecisionOut], operation_id="decisions_record")
def decisions_record(request, review_id: int, payload: DecisionIn):
    """Record (or replace) your own decision for the given articles at a stage. Article.status is not changed."""
    review = get_review(request, review_id)
    return decisions.record_decisions(
        review=review,
        article_ids=payload.ids,
        actor=request.auth,
        status=payload.status,
        stage=payload.stage,
        criteria_id=payload.selection_criteria_id,
        comments=payload.comments,
    )


@router.delete(
    "/reviews/{int:review_id}/articles/{int:article_id}/decisions/mine",
    response={204: None},
    operation_id="decisions_remove_mine",
)
def decisions_remove_mine(request, review_id: int, article_id: int, stage: str = "title_abstract"):
    decisions.remove_decision(
        review=get_review(request, review_id), article_id=article_id, actor=request.auth, stage=stage
    )
    return 204, None


@router.get(
    "/reviews/{int:review_id}/articles/{int:article_id}/decisions",
    response=list[DecisionOut],
    operation_id="article_decisions",
)
def article_decisions(request, review_id: int, article_id: int):
    return decisions.article_decisions(review=get_review(request, review_id), article_id=article_id)


@router.get(
    "/reviews/{int:review_id}/decisions/summary", response=list[DecisionSummaryOut], operation_id="decisions_summary"
)
def decisions_summary(request, review_id: int):
    return decisions.summary(get_review(request, review_id))


@router.get("/reviews/{int:review_id}/decisions/agreement", response=AgreementOut, operation_id="decisions_agreement")
def decisions_agreement(
    request, review_id: int, stage: str = "title_abstract", user_a_id: int | None = None, user_b_id: int | None = None
):
    """Cohen's kappa and percent agreement between two reviewers (default: the first two with decisions)."""
    review = get_review(request, review_id)
    return decisions.agreement(review=review, stage=stage, user_a_id=user_a_id, user_b_id=user_b_id)


@router.get(
    "/reviews/{int:review_id}/decisions/disagreements",
    response=list[DisagreementOut],
    operation_id="decisions_disagreements",
)
def decisions_disagreements(request, review_id: int, stage: str = "title_abstract"):
    """
    Articles whose reviewers disagree at the stage, with every decision. A consolidation does not remove them (it sets
    the status, not the decisions): ``article.status`` and ``article.updated_by`` tell whether one was settled.
    """
    return decisions.disagreements(review=get_review(request, review_id), stage=stage)


@router.post(
    "/reviews/{int:review_id}/decisions/consolidate", response=ConsolidateOut, operation_id="decisions_consolidate"
)
def decisions_consolidate(request, review_id: int, payload: ConsolidateIn):
    """
    Set Article.status from the decisions with a rule: unanimous, any_include or majority. ``changed`` counts the
    resolved articles whose status was different; the others already had it. The decisions are kept.
    """
    review = get_review(request, review_id)
    return decisions.consolidate(
        review=review, stage=payload.stage, rule=payload.rule, actor=request.auth, article_ids=payload.ids
    )
