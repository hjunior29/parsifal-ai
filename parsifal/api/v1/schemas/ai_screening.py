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


class JevTestOut(Schema):
    models: list[str]


class ScreeningOptionOut(Schema):
    key: str  # E1, E2… as sent to Jev
    id: int  # selection criteria id
    description: str


class ScreeningScopeOut(Schema):
    source_id: int | None  # None = all sources
    name: str
    all: int  # unclassified studies
    new: int  # unclassified studies Jev has not evaluated yet (what is sent unless rescreen)


class ScreeningContextOut(Schema):
    title: str
    objective: str
    research_questions: str  # one per line
    population: str
    intervention: str
    comparison: str
    outcome: str
    context: str


class ScreeningSetupOut(Schema):
    configured: bool  # whether you have a Jev API key
    model: str | None
    context: ScreeningContextOut  # defaults taken from the review; editable per run
    criteria: list[ScreeningOptionOut]  # fixed: the review's exclusion criteria
    none_description: str
    task: str
    rules: list[str]
    sent_fields: list[str]
    threshold_default: float
    threshold_min: float
    threshold_max: float
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
    guidance: str = ""
    threshold: float = 0.9
    source_id: int | None = None
    rescreen: bool = False


class ScreeningStepIn(Schema):
    size: int = 8  # studies screened in this step (1–50)


class ScreeningRunOut(Schema):
    id: int
    status: str  # running, finished, cancelled, failed
    model: str
    total: int
    processed: int
    excluded: int
    passed: int
    failed: int
    error: str
    started_by: str | None
    created_at: datetime
    finished_at: datetime | None


class ScreeningRunDetailOut(ScreeningRunOut):
    parameters: dict  # snapshot of what was sent: context, guidance, criteria, threshold, scope


class ScreeningResultOut(Schema):
    article_id: int
    title: str | None
    outcome: str  # excluded, passed, error, pending
    p_exclude: float | None  # 1 - p(none), averaged over the option orders
    criteria_key: str | None  # E1, E2… of the criterion Jev chose, when the study was rejected
    selection_criteria_id: int | None
    probabilities: dict | None
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
