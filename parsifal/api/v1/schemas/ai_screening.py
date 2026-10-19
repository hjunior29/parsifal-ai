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
    key: str  # E1, E2… (exclusion) or I1, I2… (inclusion), as sent to Jev
    id: int  # selection criteria id
    description: str


class ScreeningStatusOut(Schema):
    status: str  # U, R, A or D, as sent in ``statuses``
    name: str


class ScreeningScopeOut(Schema):
    source_id: int | None  # None = all sources
    name: str
    studies: int  # what a run of this phase with the default statuses would send
    by_status: dict[str, int]  # studies per status (U, R, A, D): add up the statuses you send


class ScreeningReviewerOut(Schema):
    id: int
    username: str
    name: str
    is_agent: bool


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
    phase: str  # exclusion (Exclude with AI) or inclusion (Include with AI)
    status: str  # running, finished, cancelled, failed
    reviewer_id: int
    reviewer: str  # username
    model: str
    total: int
    processed: int
    excluded: int  # rejected (both phases)
    passed: int  # exclusion: no exclusion criterion applies
    included: int  # inclusion: every inclusion criterion met
    undecided: int  # inclusion: left unclassified
    failed: int
    error: str
    started_by: str | None
    created_at: datetime
    finished_at: datetime | None


class ScreeningSetupOut(Schema):
    phase: str  # what the rest describes: exclusion or inclusion
    configured: bool  # whether you have a Jev API key
    model: str | None  # your default model
    models: list[JevModelOut]  # as listed by Jev for your key, asked now
    models_error: str  # why the list is empty, when Jev could not be asked
    reviewers: list[ScreeningReviewerOut]  # who you may screen as (the main author: anyone in the review)
    reviewer_id: int | None  # the reviewer of the latest run, preselected by the web
    unfinished_run: ScreeningRunOut | None  # a run left half-way: step it to continue, or start a new one
    unfinished_run_active: bool  # a step ran in the last seconds: something is driving it right now
    context: ScreeningContextOut  # defaults taken from the review; editable per run
    criteria: list[ScreeningOptionOut]  # fixed: the review's criteria of the phase
    none_description: str  # exclusion: the "none" option
    question_type: str  # Jev question: "choice" (exclusion: one for all criteria) or "noul" (inclusion: yes/no each)
    task: str
    rules: list[str]
    sent_fields: list[str]
    # Range and default of the thresholds: threshold (exclusion), accept_threshold and reject_threshold (inclusion).
    threshold_default: float
    threshold_min: float
    threshold_max: float
    statuses: list[ScreeningStatusOut]  # statuses of the studies a run may send
    statuses_default: list[str]  # sent when ``statuses`` is left out: R and U (exclusion), A and U (inclusion)
    scopes: list[ScreeningScopeOut]
    step_size_default: int
    step_size_max: int


class ScreeningStartIn(Schema):
    # Review context: fields left out take the review's values; "" sends the field empty.
    title: str | None = None
    objective: str | None = None
    research_questions: str | None = None
    population: str | None = None
    intervention: str | None = None
    comparison: str | None = None
    outcome: str | None = None
    context: str | None = None
    reviewer_id: int  # the decisions are recorded as this member of the review
    phase: str = "exclusion"  # exclusion (Exclude with AI) or inclusion (Include with AI)
    model: str | None = None  # default: your default model
    guidance: str = ""
    threshold: float | None = None  # exclusion: reject when 1 - p(none) is at least this (default 0.9)
    accept_threshold: float | None = None  # inclusion: accept when every p(meets) is at least this (default 0.9)
    reject_threshold: float | None = None  # inclusion: reject when some 1 - p(meets) is at least this (default 0.9)
    source_id: int | None = None
    statuses: list[str] | None = None  # studies sent: any of U, R, A, D (default R and U; inclusion: A and U)


class ScreeningStepIn(Schema):
    size: int = 8  # studies screened in this step (1–50)


class ScreeningRunDetailOut(ScreeningRunOut):
    parameters: dict  # snapshot of what was sent: context, guidance, criteria, thresholds, source and statuses


class ScreeningResultOut(Schema):
    article_id: int
    title: str | None
    previous_status: str  # the study's status when the run took it (U, R, A or D)
    outcome: str  # excluded, passed (exclusion), included, undecided (inclusion), error, pending
    p_exclude: float | None  # exclusion: 1 - p(none), averaged over the orders; inclusion: 1 - p_include
    p_include: float | None  # inclusion: the lowest p(meets) over the criteria
    criteria_key: str | None  # E1… or I1… of the criterion the study was rejected with
    selection_criteria_id: int | None
    probabilities: dict | None  # exclusion: {option: p}; inclusion: {criterion: p(meets)}
    model: str
    error: str
    processed_at: datetime | None

    @staticmethod
    def resolve_title(obj):
        return obj.article.title

    @staticmethod
    def resolve_criteria_key(obj):
        return ai_screening.criteria_key(obj.run, obj.selection_criteria_id)


class ScreeningStepOut(Schema):
    run: ScreeningRunOut
    results: list[ScreeningResultOut]
