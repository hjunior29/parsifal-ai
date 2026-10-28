"""
Exclude with AI, Include with AI and Screen with AI (both in one request), in no particular order, and the Jev
integration they need. The same
operations as the web: the user's Jev key (Settings → Integrations) and runs started and advanced step by step from
the study selection page; an interrupted run is continued by stepping it again. Runs use the Jev key of whoever
calls the endpoint. As the AI runs window: what a run would rewrite before starting it, running one again with its
settings, and undoing the latest one (see ``services/ai_runs.py``).
"""

from ninja import Router
from ninja.pagination import LimitOffsetPagination, paginate

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.ai_screening import (
    JevIntegrationIn,
    JevIntegrationOut,
    JevTestIn,
    JevTestOut,
    ScreeningImpactIn,
    ScreeningImpactOut,
    ScreeningPreviewIn,
    ScreeningPreviewOut,
    ScreeningRerunIn,
    ScreeningResultOut,
    ScreeningRunDetailOut,
    ScreeningRunOut,
    ScreeningSetupOut,
    ScreeningStartIn,
    ScreeningStepIn,
    ScreeningStepOut,
    ScreeningUndoOut,
)
from parsifal.apps.accounts import services as integrations
from parsifal.apps.reviews.services import ai_runs, ai_screening, screening_requests

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


def _run_out(request, run, detail=False, controls=None):
    """``controls``: ``ai_runs.controls`` of the runs listed together (computed for this run when left out)."""
    control = (controls or ai_runs.controls(run.review, request.auth, [run]))[run.pk]
    data = dict(
        ai_screening.progress(run),
        reviewer_id=run.reviewer_id,
        reviewer=run.reviewer.username,
        model=run.model,
        started_by=run.started_by.username if run.started_by else None,
        created_at=run.created_at,
        finished_at=run.finished_at,
        standing=control["standing"],
        undoable=not control["undo_problem"],
        undo_blocked=control["undo_problem"],
    )
    if detail:
        return ScreeningRunDetailOut(parameters=run.parameters, **data)
    return ScreeningRunOut(**data)


def _settings(payload):
    """The settings of a run (or a preview) that shape the request, as ``start_run`` takes them."""
    fields = payload.dict()
    return {
        "phase": payload.phase,
        "model": payload.model,
        "context": {name: fields[name] for name, _label, _limit in ai_screening.CONTEXT_FIELDS},
        "guidance": payload.guidance,
        "template": payload.template,
        "source_id": payload.source_id,
        "statuses": payload.statuses,
        "criteria_ids": payload.criteria_ids,
        "defaults": payload.defaults,
    }


@router.get("/reviews/{int:review_id}/ai-screening", response=ScreeningSetupOut, operation_id="ai_screening_setup")
def ai_screening_setup(request, review_id: int, phase: str = "exclusion", defaults: bool = False):
    """
    What a run of ``phase`` (exclusion, inclusion or screen) would use. ``start``: every setting it starts from — those
    of the review's last run of that action (reviewer, model, context, guidance, request template, thresholds,
    criteria sent, source, statuses), or Parsifal's defaults with ``defaults`` (or when there is no run yet); the
    start operation takes them for whatever it leaves out. Also the review's criteria of the action (exclusion: E1,
    E2… plus none in one choice question; inclusion: I1, I2…, one yes/no question each, answered with the probability
    that the study meets it; screen: both in one request), the protocol's inclusion rule (all or any), Parsifal's
    request template, the threshold's range, Jev's models for your key, who you may screen as, and how many studies
    each source has per status.
    """
    review = get_review(request, review_id)
    phase = ai_screening.clean_phase(phase)
    start = ai_screening.starting_settings(review, phase, defaults=defaults)
    threshold_default, threshold_min, threshold_max, inclusion_threshold_min = ai_screening.threshold_range()
    integration = integrations.get_jev(request.auth)
    models, models_error = integrations.jev_models(request.auth) if integration else ([], "")
    agent_ids = ai_screening.agent_ids(review)
    choices = ai_screening.reviewer_choices(review, request.auth)
    counts = ai_screening.scope_counts(review)
    unfinished = ai_screening.unfinished_run(review)

    def scope(source_id, name, by_status):
        studies = sum(by_status[status] for status in ai_screening.DEFAULT_STATUSES[phase])
        return {"source_id": source_id, "name": name, "studies": studies, "by_status": by_status}

    empty = {code: 0 for code, _label in ai_screening.STATUSES}
    scopes = [scope(None, "All sources", counts[""])]
    for source in review.sources.order_by("name"):
        scopes.append(scope(source.pk, source.name, counts.get(str(source.pk), empty)))
    context = ai_screening.default_context(review)
    context.update({name: value for name, value in (start["context"] or {}).items() if value is not None})
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
        unfinished_run=_run_out(request, unfinished) if unfinished else None,
        unfinished_run_active=bool(unfinished and ai_screening.is_active(unfinished)),
        start={
            "from_run_id": start["run"].pk if start["run"] else None,
            "reviewer_id": start["reviewer_id"] if start["reviewer_id"] in {m.pk for m in choices} else None,
            "model": start["model"],
            "context": context,
            "guidance": start["guidance"],
            "template": start["template"],
            "threshold": start["threshold"],
            "thresholds": start["thresholds"] or {},
            "source_id": start["source_id"],
            "statuses": start["statuses"] or ai_screening.clean_statuses(None, phase),
            "criteria_ids": start["criteria_ids"],
        },
        criteria=ai_screening.criteria_options(review, phase),
        inclusion_rule=review.inclusion_rule,
        question_type=screening_requests.QUESTION_TYPES[phase],
        template_default=screening_requests.default(phase),
        placeholders=[
            {"name": name, "description": description} for name, description in screening_requests.PLACEHOLDERS
        ],
        threshold_default=threshold_default,
        threshold_min=threshold_min,
        threshold_max=threshold_max,
        inclusion_threshold_min=inclusion_threshold_min,
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
    Open a run of ``phase`` (exclusion, default; inclusion; or screen) in the name of ``reviewer_id``; the reviewer's
    earlier decisions on the studies sent are rewritten. Whatever is left out takes the settings of the review's last
    run of that action (see the setup's ``start``), or Parsifal's defaults with ``defaults``. ``criteria_ids``: the
    criteria sent (leave out those Jev cannot judge from a title and abstract). Exclusion rejects when some exclusion
    criterion applies with at least ``threshold`` (0.5–0.99). Inclusion accepts when the inclusion criteria are met,
    each with at least its own threshold (``thresholds``, 0.01–0.99, e.g. {"I1": 0.9, "I2": 0.85}) — every one of them,
    or at least one with the protocol's rule "any" —, and never rejects. Screen asks both in one request: rejected when
    the exclusion threshold is reached (even when the inclusion criteria are met), else accepted when the inclusion
    criteria are met, else left unclassified. Only unclassified studies and those this reviewer classified change
    status (exclusion: its rejections; inclusion: its acceptances; screen: both); the others only get the reviewer's
    decision. Only the main author may name another member. ``template`` is the request sent about each study (see the
    setup and the preview operation). Nothing is screened yet: call the step operation until the run is no longer
    running.
    """
    review = get_review(request, review_id)
    run = ai_screening.start_run(
        review=review,
        actor=request.auth,
        reviewer_id=payload.reviewer_id,
        threshold=payload.threshold,
        thresholds=payload.thresholds,
        **_settings(payload),
    )
    return 201, _run_out(request, run, detail=True)


@router.post(
    "/reviews/{int:review_id}/ai-screening/preview",
    response=ScreeningPreviewOut,
    operation_id="ai_screening_preview",
)
def ai_screening_preview(request, review_id: int, payload: ScreeningPreviewIn):
    """
    The request a run with these settings would send to Jev (the body of its POST /v1/systemone: model, state and
    questions) about ``article_id``, or else the first study in scope with a title or abstract. Nothing is sent: use
    it to check an edited ``template`` before starting a run.
    """
    review = get_review(request, review_id)
    preview = ai_screening.preview(
        review=review, actor=request.auth, article_id=payload.article_id, **_settings(payload)
    )
    article = preview["article"]
    return ScreeningPreviewOut(article_id=article.pk, title=article.title, request=preview["request"])


@router.get(
    "/reviews/{int:review_id}/ai-screening/runs", response=list[ScreeningRunOut], operation_id="ai_screening_runs_list"
)
def ai_screening_runs_list(request, review_id: int):
    """
    Runs of the review, newest first, each with how many of its decisions still stand and whether you can undo it.
    """
    review = get_review(request, review_id)
    runs = list(ai_screening.list_runs(review))
    controls = ai_runs.controls(review, request.auth, runs)
    return [_run_out(request, run, controls=controls) for run in runs]


@router.get(
    "/reviews/{int:review_id}/ai-screening/runs/{int:run_id}",
    response=ScreeningRunDetailOut,
    operation_id="ai_screening_runs_get",
)
def ai_screening_runs_get(request, review_id: int, run_id: int):
    """One run: progress, how it ended, the parameters sent and whether it can be undone."""
    return _run_out(request, ai_screening.get_run(get_review(request, review_id), run_id), detail=True)


@router.post(
    "/reviews/{int:review_id}/ai-screening/runs/{int:run_id}/step",
    response=ScreeningStepOut,
    operation_id="ai_screening_step",
)
def ai_screening_step(request, review_id: int, run_id: int, payload: ScreeningStepIn):
    """
    Screen the next studies of the run (size 1–64) with your Jev key. Exclusion: studies whose p_exclude reaches the
    threshold get the reviewer's "rejected" decision, the rest "unclassified". Inclusion: "accepted" when the
    criteria's p(meets) reach their thresholds (all of them, or one with the rule "any"), else "unclassified"
    (outcome undecided); nothing is rejected. Screen: "rejected" (outcome excluded) when p_exclude reaches the
    exclusion threshold, else "accepted" (included) when the inclusion criteria are met, else "unclassified"
    (undecided). The status follows as described in the start operation.
    The run finishes when no study is left. If Jev refuses the key or is unavailable, the run keeps its remaining
    studies and ``run.error`` says why: call step again to continue (also for a run interrupted in the web).
    """
    run = ai_screening.get_run(get_review(request, review_id), run_id)
    results = ai_screening.process_step(run=run, actor=request.auth, size=payload.size)
    return ScreeningStepOut(run=_run_out(request, run), results=results)


@router.get(
    "/reviews/{int:review_id}/ai-screening/runs/{int:run_id}/results",
    response=list[ScreeningResultOut],
    operation_id="ai_screening_results",
)
@paginate(LimitOffsetPagination)
def ai_screening_results(request, review_id: int, run_id: int, outcome: str | None = None):
    """
    What Jev answered for each study of the run; filter by outcome (excluded, passed, included, undecided, error,
    pending).
    """
    run = ai_screening.get_run(get_review(request, review_id), run_id)
    return ai_screening.list_results(run, outcome=outcome)


@router.post(
    "/reviews/{int:review_id}/ai-screening/impact",
    response=ScreeningImpactOut,
    operation_id="ai_screening_impact",
)
def ai_screening_impact(request, review_id: int, payload: ScreeningImpactIn):
    """
    What a run would rewrite, to confirm before starting it (nothing is started): of the studies it would send
    (``phase``, ``statuses``, ``source_id`` as in the start operation, the last run's when left out), how many have a
    decision of ``reviewer_id``, which the run replaces, and how many that reviewer classified with a status the run
    may change. ``confirm`` is true when either is not zero. With ``run_id``, for the rerun operation: that run's
    settings fill in the rest.
    """
    review = get_review(request, review_id)
    return ai_runs.impact(review=review, actor=request.auth, **payload.dict())


@router.post(
    "/reviews/{int:review_id}/ai-screening/runs/{int:run_id}/rerun",
    response={201: ScreeningRunDetailOut},
    operation_id="ai_screening_rerun",
)
def ai_screening_rerun(request, review_id: int, run_id: int, payload: ScreeningRerunIn):
    """
    Open a new run with the settings of run ``run_id`` (action, reviewer, model, context, guidance, request template,
    thresholds, criteria sent, source and statuses), changing those given; the criteria are the review's current ones
    (those the run left out stay out). As the start operation: nothing is screened yet, call the step operation until
    the run is no longer running. A Retain with AI run cannot be run again (the action was removed).
    """
    review = get_review(request, review_id)
    run = ai_runs.rerun(review=review, actor=request.auth, run_id=run_id, **payload.dict())
    return 201, _run_out(request, run, detail=True)


@router.get(
    "/reviews/{int:review_id}/ai-screening/runs/{int:run_id}/undo",
    response=ScreeningUndoOut,
    operation_id="ai_screening_undo_preview",
)
def ai_screening_undo_preview(request, review_id: int, run_id: int):
    """What undoing the run would do (see the undo operation), without doing it."""
    return ai_runs.undo_preview(review=get_review(request, review_id), actor=request.auth, run_id=run_id)


@router.post(
    "/reviews/{int:review_id}/ai-screening/runs/{int:run_id}/undo",
    response=ScreeningUndoOut,
    operation_id="ai_screening_undo",
)
def ai_screening_undo(request, review_id: int, run_id: int):
    """
    Undo the review's latest run where its evaluation still stands, then delete it with its answers; the run before
    it becomes the latest, which can be undone next. The reviewer's decisions that are still the run's go back to the
    ones it replaced (or are removed when there were none); the studies whose status it changed go back to their
    status, criterion and last editor from before, unless someone changed them since. Decisions replaced since,
    studies changed since and other reviewers' decisions are not touched. Only the latest run (422 for the others),
    started since Parsifal keeps what came before a run (``undoable`` in the run), by the main author or the run's
    reviewer, and not while a run is being screened (409). It cannot be undone.
    """
    return ai_runs.undo_run(review=get_review(request, review_id), actor=request.auth, run_id=run_id)
