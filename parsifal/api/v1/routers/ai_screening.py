"""
Exclude with AI (phase 1 of study selection) and the Jev integration it needs. The same operations as the web: the
user's Jev key (Settings → Integrations) and runs started, advanced step by step and cancelled from the study
selection page. Runs use the Jev key of whoever calls the endpoint.
"""

from ninja import Router
from ninja.pagination import LimitOffsetPagination, paginate

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.ai_screening import (
    JevIntegrationIn,
    JevIntegrationOut,
    JevTestOut,
    ScreeningResultOut,
    ScreeningRunDetailOut,
    ScreeningRunOut,
    ScreeningSetupOut,
    ScreeningStartIn,
    ScreeningStepIn,
    ScreeningStepOut,
)
from parsifal.apps.accounts import services as integrations
from parsifal.apps.reviews.services import ai_screening

router = Router(tags=["ai screening"])


def _integration_out(integration):
    if integration is None:
        return JevIntegrationOut(configured=False)
    return JevIntegrationOut(
        configured=True, masked_key=integration.masked_key, model=integration.model, updated_at=integration.updated_at
    )


@router.get("/integrations/jev", response=JevIntegrationOut, operation_id="jev_integration_get")
def jev_integration_get(request):
    """Your Jev integration: whether a key is saved (only its last characters), the model and when it changed."""
    return _integration_out(integrations.get_jev(request.auth))


@router.put("/integrations/jev", response=JevIntegrationOut, operation_id="jev_integration_set")
def jev_integration_set(request, payload: JevIntegrationIn):
    """Save or replace your Jev API key and/or model. Pin a version (jev-1.13.0); aliases change without notice."""
    return _integration_out(integrations.save_jev(request.auth, api_key=payload.api_key, model=payload.model))


@router.post("/integrations/jev/test", response=JevTestOut, operation_id="jev_integration_test")
def jev_integration_test(request):
    """Check the saved key with Jev; returns the models it can use (422 if Jev rejects the key, 502 if Jev fails)."""
    return JevTestOut(models=integrations.test_jev(request.auth))


@router.delete("/integrations/jev", response={204: None}, operation_id="jev_integration_delete")
def jev_integration_delete(request):
    """Remove your Jev API key. Decisions already made stay."""
    integrations.remove_jev(request.auth)
    return 204, None


def _run_out(run, detail=False):
    data = dict(
        ai_screening.progress(run),
        model=run.model,
        started_by=run.started_by.username if run.started_by else None,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )
    if detail:
        return ScreeningRunDetailOut(parameters=run.parameters, **data)
    return ScreeningRunOut(**data)


@router.get("/reviews/{int:review_id}/ai-screening", response=ScreeningSetupOut, operation_id="ai_screening_setup")
def ai_screening_setup(request, review_id: int):
    """
    What a run would send: the review context (editable per run), the exclusion criteria as options E1, E2… plus
    none (fixed), the task and rules (fixed), the threshold range and how many studies each scope would send.
    """
    review = get_review(request, review_id)
    integration = integrations.get_jev(request.auth)
    counts = ai_screening.scope_counts(review)
    scopes = [{"source_id": None, "name": "All sources", **counts[""]}]
    for source in review.sources.order_by("name"):
        scopes.append(
            {"source_id": source.pk, "name": source.name, **counts.get(str(source.pk), {"all": 0, "new": 0})}
        )
    return ScreeningSetupOut(
        configured=integration is not None,
        model=integration.model if integration else None,
        context=ai_screening.default_context(review),
        criteria=ai_screening.exclusion_options(review),
        none_description=ai_screening.NONE_DESCRIPTION,
        task=ai_screening.TASK,
        rules=list(ai_screening.RULES),
        sent_fields=list(ai_screening.SENT_FIELDS),
        threshold_default=ai_screening.DEFAULT_THRESHOLD,
        threshold_min=ai_screening.MIN_THRESHOLD,
        threshold_max=ai_screening.MAX_THRESHOLD,
        scopes=scopes,
        step_size_default=ai_screening.STEP_SIZE,
        step_size_max=ai_screening.MAX_STEP_SIZE,
    )


@router.post(
    "/reviews/{int:review_id}/ai-screening/runs",
    response={201: ScreeningRunDetailOut},
    operation_id="ai_screening_start",
)
def ai_screening_start(request, review_id: int, payload: ScreeningStartIn):
    """
    Open a run over the unclassified studies in scope (skipping those Jev already evaluated unless rescreen).
    Nothing is screened yet: call the step operation until the run is no longer running.
    """
    review = get_review(request, review_id)
    fields = payload.dict()
    context = {name: fields[name] for name, _label, _limit in ai_screening.CONTEXT_FIELDS}
    run = ai_screening.start_run(
        review=review,
        actor=request.auth,
        context=context,
        guidance=payload.guidance,
        threshold=payload.threshold,
        source_id=payload.source_id,
        rescreen=payload.rescreen,
    )
    return 201, _run_out(run, detail=True)


@router.get(
    "/reviews/{int:review_id}/ai-screening/runs", response=list[ScreeningRunOut], operation_id="ai_screening_runs_list"
)
def ai_screening_runs_list(request, review_id: int):
    """Runs of the review, newest first."""
    review = get_review(request, review_id)
    return [_run_out(run) for run in ai_screening.list_runs(review)]


@router.get(
    "/reviews/{int:review_id}/ai-screening/runs/{int:run_id}",
    response=ScreeningRunDetailOut,
    operation_id="ai_screening_runs_get",
)
def ai_screening_runs_get(request, review_id: int, run_id: int):
    """One run: progress, how it ended and the parameters sent."""
    return _run_out(ai_screening.get_run(get_review(request, review_id), run_id), detail=True)


@router.post(
    "/reviews/{int:review_id}/ai-screening/runs/{int:run_id}/step",
    response=ScreeningStepOut,
    operation_id="ai_screening_step",
)
def ai_screening_step(request, review_id: int, run_id: int, payload: ScreeningStepIn):
    """
    Screen the next studies of the run (size 1–50) with your Jev key. Studies at or above the threshold are rejected
    as the review's Jev agent; the rest stay unclassified. The run finishes when no study is left.
    """
    run = ai_screening.get_run(get_review(request, review_id), run_id)
    results = ai_screening.process_step(run=run, actor=request.auth, size=payload.size)
    return ScreeningStepOut(run=_run_out(run), results=results)


@router.post(
    "/reviews/{int:review_id}/ai-screening/runs/{int:run_id}/cancel",
    response=ScreeningRunOut,
    operation_id="ai_screening_cancel",
)
def ai_screening_cancel(request, review_id: int, run_id: int):
    """Stop the run; what was already screened stays, the rest is not sent."""
    run = ai_screening.get_run(get_review(request, review_id), run_id)
    return _run_out(ai_screening.cancel_run(run=run))


@router.get(
    "/reviews/{int:review_id}/ai-screening/runs/{int:run_id}/results",
    response=list[ScreeningResultOut],
    operation_id="ai_screening_results",
)
@paginate(LimitOffsetPagination)
def ai_screening_results(request, review_id: int, run_id: int, outcome: str | None = None):
    """What Jev answered for each study of the run; filter by outcome (excluded, passed, error, pending)."""
    run = ai_screening.get_run(get_review(request, review_id), run_id)
    return ai_screening.list_results(run, outcome=outcome)
