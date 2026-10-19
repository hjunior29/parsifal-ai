"""
Exclude with AI (phase 1 of study selection), Include with AI (phase 2) and the Jev integration they need. The same
operations as the web: the user's Jev key (Settings → Integrations) and runs started and advanced step by step from
the study selection page; an interrupted run is continued by stepping it again. Runs use the Jev key of whoever
calls the endpoint.
"""

from ninja import Router
from ninja.pagination import LimitOffsetPagination, paginate

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.ai_screening import (
    JevIntegrationIn,
    JevIntegrationOut,
    JevTestIn,
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
def jev_integration_test(request, payload: JevTestIn):
    """
    Ask Jev which models a key can use: ``api_key`` if given (nothing is saved), else your saved key. 422 if Jev
    rejects the key, 502 if Jev fails.
    """
    return JevTestOut(models=integrations.test_jev(request.auth, api_key=payload.api_key))


@router.delete("/integrations/jev", response={204: None}, operation_id="jev_integration_delete")
def jev_integration_delete(request):
    """Remove your Jev API key. Decisions already made stay."""
    integrations.remove_jev(request.auth)
    return 204, None


def _run_out(run, detail=False):
    data = dict(
        ai_screening.progress(run),
        reviewer_id=run.reviewer_id,
        reviewer=run.reviewer.username,
        model=run.model,
        started_by=run.started_by.username if run.started_by else None,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )
    if detail:
        return ScreeningRunDetailOut(parameters=run.parameters, **data)
    return ScreeningRunOut(**data)


@router.get("/reviews/{int:review_id}/ai-screening", response=ScreeningSetupOut, operation_id="ai_screening_setup")
def ai_screening_setup(request, review_id: int, phase: str = "exclusion"):
    """
    What a run of ``phase`` would send: the review context (editable per run), the criteria (fixed; exclusion: E1,
    E2… plus none in one question; inclusion: I1, I2…, one question each answered meets, not_met or unclear), the
    task and rules (fixed), Jev's models for your key, who you may screen as, and how many studies each source has
    per status (a run sends the statuses you choose).
    """
    review = get_review(request, review_id)
    phase = ai_screening.clean_phase(phase)
    task, rules = ai_screening.task_and_rules(phase)
    integration = integrations.get_jev(request.auth)
    models, models_error = integrations.jev_models(request.auth) if integration else ([], "")
    agent_ids = ai_screening.agent_ids(review)
    choices = ai_screening.reviewer_choices(review, request.auth)
    last = ai_screening.last_reviewer_id(review)
    reviewer = next((member for member in choices if member.pk == last), None)
    counts = ai_screening.scope_counts(review)
    unfinished = ai_screening.unfinished_run(review)

    def scope(source_id, name, by_status):
        studies = sum(by_status[status] for status in ai_screening.DEFAULT_STATUSES[phase])
        return {"source_id": source_id, "name": name, "studies": studies, "by_status": by_status}

    empty = {code: 0 for code, _label in ai_screening.STATUSES}
    scopes = [scope(None, "All sources", counts[""])]
    for source in review.sources.order_by("name"):
        scopes.append(scope(source.pk, source.name, counts.get(str(source.pk), empty)))
    inclusion = phase == ai_screening.INCLUSION
    return ScreeningSetupOut(
        phase=phase,
        configured=integration is not None,
        model=integration.model if integration else None,
        models=models,
        models_error=models_error,
        reviewers=[
            {
                "id": member.pk,
                "username": member.username,
                "name": member.get_full_name() or member.username,
                "is_agent": member.pk in agent_ids,
            }
            for member in choices
        ],
        reviewer_id=reviewer.pk if reviewer else None,
        unfinished_run=_run_out(unfinished) if unfinished else None,
        unfinished_run_active=bool(unfinished and ai_screening.is_active(unfinished)),
        context=ai_screening.default_context(review),
        criteria=ai_screening.criteria_options(review, phase),
        none_description="" if inclusion else ai_screening.NONE_DESCRIPTION,
        answers=[ai_screening.MEETS, ai_screening.NOT_MET, ai_screening.UNCLEAR] if inclusion else [],
        unclear_description=ai_screening.UNCLEAR_DESCRIPTION if inclusion else "",
        task=task,
        rules=list(rules),
        sent_fields=list(ai_screening.SENT_FIELDS),
        threshold_default=ai_screening.DEFAULT_THRESHOLD,
        threshold_min=ai_screening.MIN_THRESHOLD,
        threshold_max=ai_screening.MAX_THRESHOLD,
        statuses=[{"status": code, "name": label} for code, label in ai_screening.STATUSES],
        statuses_default=ai_screening.clean_statuses(None, phase),
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
    Open a run of ``phase`` (exclusion, default, or inclusion) in the name of ``reviewer_id`` over the studies in
    scope with ``statuses`` (U, R, A, D; default R and U for exclusion, A and U for inclusion); the reviewer's earlier
    decisions on them are rewritten. Only unclassified studies and those this reviewer classified change status
    (exclusion: its rejections; inclusion: its acceptances and rejections); the others only get the reviewer's
    decision. Only the main author may name another member. Nothing is screened yet: call the step operation until
    the run is no longer running.
    """
    review = get_review(request, review_id)
    fields = payload.dict()
    context = {name: fields[name] for name, _label, _limit in ai_screening.CONTEXT_FIELDS}
    run = ai_screening.start_run(
        review=review,
        actor=request.auth,
        reviewer_id=payload.reviewer_id,
        model=payload.model,
        context=context,
        guidance=payload.guidance,
        threshold=payload.threshold,
        source_id=payload.source_id,
        statuses=payload.statuses,
        phase=payload.phase,
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
    Screen the next studies of the run (size 1–50) with your Jev key. Exclusion: studies whose p_exclude reaches the
    threshold get the reviewer's "rejected" decision, the rest "unclassified". Inclusion: "accepted" when the lowest
    p(meets) reaches it, else "rejected" when some p(not_met) reaches it (that criterion is the reason), else
    "unclassified". The status follows as described in the start operation. The run finishes when no study is
    left. If Jev refuses the key or is unavailable, the run keeps its remaining studies and ``run.error`` says why:
    call step again to continue (also for a run interrupted in the web).
    """
    run = ai_screening.get_run(get_review(request, review_id), run_id)
    results = ai_screening.process_step(run=run, actor=request.auth, size=payload.size)
    return ScreeningStepOut(run=_run_out(run), results=results)


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
