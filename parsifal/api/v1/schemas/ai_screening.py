from datetime import datetime

from ninja import Schema

from parsifal.apps.reviews.services import ai_screening


class JevIntegrationIn(Schema):
    api_key: str | None = None  # blank keeps the saved key (required the first time)
    model: str | None = None  # blank keeps the saved model (jev-1.13.0 the first time)


class JevIntegrationOut(Schema):
    configured: bool
    masked_key: str | None = None  # last characters only; the key itself is never returned
    model: str | None = None
    updated_at: datetime | None = None


class JevModelOut(Schema):
    name: str
    description: str
    release_date: str


class JevTestIn(Schema):
    api_key: str | None = None  # test this key instead of the saved one (nothing is saved)


class JevTestOut(Schema):
    models: list[JevModelOut]  # as listed by Jev for your key


class ScreeningOptionOut(Schema):
    key: str  # E1, E2… (exclusion) or I1, I2… (inclusion), as sent to Jev; screen sends both
    id: int  # selection criteria id
    description: str


class ScreeningStatusOut(Schema):
    status: str  # U, R, A or D, as sent in ``statuses``
    name: str


class ScreeningScopeOut(Schema):
    source_id: int | None  # None = all sources
    name: str
    studies: int  # what a run of this action with its default statuses would send
    by_status: dict[str, int]  # studies per status (U, R, A, D): add up the statuses you send


class ScreeningReviewerOut(Schema):
    id: int
    username: str
    name: str
    is_agent: bool


class ScreeningPlaceholderOut(Schema):
    name: str  # written {{name}} in a request template
    description: str


class ScreeningContextOut(Schema):
    title: str
    objective: str
    research_questions: str  # one per line
    population: str
    intervention: str
    comparison: str
    outcome: str
    context: str


class ScreeningRunOut(Schema):
    id: int
    # exclusion (Exclude with AI), inclusion (Include with AI), screen (Screen with AI); retention (Retain with AI,
    # removed) in older runs
    phase: str
    status: str  # running, finished, cancelled, failed
    reviewer_id: int
    reviewer: str  # username
    model: str
    total: int
    processed: int
    excluded: int  # exclusion and screen: rejected with a criterion (inclusion never rejects)
    passed: int  # exclusion: no exclusion criterion applies
    included: int  # inclusion and screen: the inclusion criteria met, accepted
    undecided: int  # inclusion and screen: left unclassified
    failed: int
    error: str
    started_by: str | None
    created_at: datetime
    finished_at: datetime | None
    # Decisions of the reviewer that are still this run's (nobody replaced them since); None for runs made before
    # Parsifal kept what came before a run, which cannot be undone.
    standing: int | None
    undoable: bool  # whether you can undo it now: only the review's latest run can be (see the undo operations)
    undo_blocked: str  # why not, when undoable is false


class ScreeningStartSettingsOut(Schema):
    """What a run of the action starts from when you leave a setting out: the review's last run of that action."""

    from_run_id: int | None  # the run these settings come from; null: Parsifal's defaults (no run yet, or defaults)
    reviewer_id: int | None
    model: str | None  # null: your default model
    context: ScreeningContextOut
    guidance: str
    template: dict  # the request sent about each study
    threshold: float | None  # the exclusion threshold (exclusion and screen)
    thresholds: dict[str, float]  # the threshold of each inclusion criterion (inclusion and screen)
    source_id: int | None  # null: all sources
    statuses: list[str]
    criteria_ids: list[int]  # the criteria sent; the others are left out


class ScreeningSetupOut(Schema):
    phase: str  # what the rest describes: exclusion, inclusion or screen
    configured: bool  # whether you have a Jev API key
    model: str | None  # your default model
    models: list[JevModelOut]  # as listed by Jev for your key, asked now
    models_error: str  # why the list is empty, when Jev could not be asked
    reviewers: list[ScreeningReviewerOut]  # who you may screen as (the main author: anyone in the review)
    unfinished_run: ScreeningRunOut | None  # a run left half-way: step it to continue, or start a new one
    unfinished_run_active: bool  # a step ran in the last seconds: something is driving it right now
    # Every setting a run starts from: those of the review's last run of the action, or Parsifal's defaults with
    # ``defaults=true``. The start operation takes them for whatever it leaves out.
    start: ScreeningStartSettingsOut
    # The review's criteria of the action (screen: exclusion and inclusion); ``start.criteria_ids`` are those sent.
    criteria: list[ScreeningOptionOut]
    inclusion_rule: str  # all: a study must meet every inclusion criterion; any: at least one (set in the protocol)
    # Jev questions: "choice" (exclusion: one for all criteria), "noul" (inclusion: yes/no each), "choice+noul"
    # (screen: both in one request)
    question_type: str
    template_default: dict  # Parsifal's request template; ``start.template`` is the one a run starts from
    placeholders: list[ScreeningPlaceholderOut]
    threshold_default: float
    threshold_min: float
    threshold_max: float
    statuses: list[ScreeningStatusOut]  # statuses of the studies a run may send
    # Parsifal's default statuses: R and U (exclusion), A and U (inclusion), A, R and U (screen).
    statuses_default: list[str]
    scopes: list[ScreeningScopeOut]
    step_size_default: int
    step_size_max: int


class ScreeningSettingsIn(Schema):
    # Whatever is left out takes the settings of the review's last run of the action (see the setup's ``start``), or
    # Parsifal's defaults with ``defaults``.
    # Review context: fields left out keep the last run's (or the review's); "" sends the field empty.
    title: str | None = None
    objective: str | None = None
    research_questions: str | None = None
    population: str | None = None
    intervention: str | None = None
    comparison: str | None = None
    outcome: str | None = None
    context: str | None = None
    phase: str = "exclusion"  # exclusion (Exclude with AI), inclusion (Include with AI) or screen (Screen with AI)
    model: str | None = None
    guidance: str | None = None
    # The request sent about each study (an object or its JSON text), as the setup's ``start.template``: edit the
    # text around the {{placeholders}}.
    template: dict | str | None = None
    source_id: int | None = None  # 0: all sources
    # Studies sent: any of U, R, A, D (Parsifal's defaults: R and U; inclusion: A and U; screen: A, R and U).
    statuses: list[str] | None = None
    # The criteria sent (ids, as the setup's ``criteria``): leave out those Jev cannot judge from a title and abstract.
    criteria_ids: list[int] | None = None
    defaults: bool = False  # what is left out takes Parsifal's defaults instead of the last run's settings


class ScreeningStartIn(ScreeningSettingsIn):
    reviewer_id: int  # the decisions are recorded as this member of the review
    # Exclusion and screen: reject when 1 - p(none) is at least this (0.5–0.99). Inclusion: the threshold of the
    # criteria that ``thresholds`` leaves out.
    threshold: float | None = None
    # Inclusion and screen: the threshold of each inclusion criterion sent, {"I1": 0.9, "I2": 0.85} or
    # ["I1=0.9", "I2=0.85"]; accept when every p(meets) reaches its own (or one of them, with the protocol's rule
    # "any"). Criteria left out take the last run's, else 0.9 (inclusion: ``threshold`` when given).
    thresholds: dict[str, float] | list[str] | None = None


class ScreeningPreviewIn(ScreeningSettingsIn):
    article_id: int | None = None  # this study; default: the first one in scope with a title or abstract


class ScreeningPreviewOut(Schema):
    article_id: int
    title: str | None
    request: dict  # the body of POST /v1/systemone: model, state and questions


class ScreeningStepIn(Schema):
    size: int = ai_screening.STEP_SIZE  # studies screened in this step (1–64, default 64)


class ScreeningRunDetailOut(ScreeningRunOut):
    # Snapshot of what was sent: context, guidance, criteria, request template, threshold, source and statuses.
    parameters: dict


class ScreeningResultOut(Schema):
    article_id: int
    title: str | None
    previous_status: str  # the study's status when the run took it (U, R, A or D)
    # excluded, passed (exclusion), included, undecided (inclusion), excluded, included, undecided (screen), error,
    # pending; older Retain with AI runs: included (retained), excluded (not retained)
    outcome: str
    p_exclude: float | None  # exclusion and screen: 1 - p(none)
    # Inclusion and screen: p(meets) of the deciding criterion — rule "all": the one closest to (or furthest below)
    # its threshold; rule "any": the one furthest above (or closest to) it. Older retention runs: p(retain).
    p_include: float | None
    # The status the run gave the study, as the study list names them (the reviewer's decision): R, A or U; null when
    # it was not screened (pending, error). ``outcome`` says which answer led there.
    status: str | None = None
    kept_status: str | None = None  # the status the study kept instead, when the run could not change it
    criteria_key: str | None  # E1… of the criterion the study was rejected with
    selection_criteria_id: int | None
    # exclusion: {option: p}; inclusion: {criterion: p(meets)}; screen: both; older retention runs: {retain: p}
    probabilities: dict | None
    model: str
    error: str
    processed_at: datetime | None

    @staticmethod
    def resolve_title(obj):
        return obj.article.title

    @staticmethod
    def resolve_status(obj):
        return ai_screening.result_status(obj)

    @staticmethod
    def resolve_kept_status(obj):
        return ai_screening.kept_status(obj)

    @staticmethod
    def resolve_criteria_key(obj):
        return ai_screening.criteria_key(obj.run, obj.selection_criteria_id)


class ScreeningStepOut(Schema):
    run: ScreeningRunOut
    results: list[ScreeningResultOut]


class ScreeningUndoOut(Schema):
    run_id: int
    phase: str
    reviewer_id: int
    reviewer: str  # username
    screened: int  # studies the run evaluated (errors and pending studies did nothing)
    statuses_restored: int  # studies that go back to their status from before the run (nobody changed them since)
    back_to: dict[str, int]  # of those, how many go back to each status (U, R, A)
    statuses_kept: int  # studies whose status changed again since the run: they keep it
    decisions_restored: int  # the reviewer's decisions that go back to the ones the run replaced
    decisions_removed: int  # the reviewer's decisions removed (there was none before the run)
    decisions_kept: int  # the reviewer's decisions replaced since the run: they stay
    message: str  # all of the above in a few sentences


class ScreeningImpactIn(Schema):
    phase: str | None = None  # exclusion (default), inclusion or screen
    reviewer_id: int | None = None  # who the decisions would be recorded as
    statuses: list[str] | None = None  # studies sent: U, R, A, D (left out: the last run's, as the start operation)
    source_id: int | None = None  # 0: all sources
    run_id: int | None = None  # a run to do again (see the rerun operation): its settings fill in what is left out
    defaults: bool = False  # what is left out takes Parsifal's defaults instead of the last run's settings


class ScreeningImpactOut(Schema):
    phase: str
    reviewer_id: int
    reviewer: str  # username
    studies: int  # studies the run would send
    decisions: int  # of those, studies with a decision of the reviewer, which the run would replace
    classified: int  # of those, studies the reviewer classified with a status the run may change
    confirm: bool  # decisions or classified is not zero: ask before starting
    message: str


class ScreeningRerunIn(Schema):
    # Everything left out is the run's: action, reviewer, model, context, guidance, request template, thresholds,
    # source, statuses and criteria (those it left out stay out; a criterion added since is sent).
    reviewer_id: int | None = None
    model: str | None = None
    threshold: float | None = None  # exclusion and screen: the exclusion threshold; inclusion: replaces them all
    thresholds: dict[str, float] | list[str] | None = None  # inclusion criteria: see the start operation
    statuses: list[str] | None = None
    source_id: int | None = None  # 0: all sources
    criteria_ids: list[int] | None = None
