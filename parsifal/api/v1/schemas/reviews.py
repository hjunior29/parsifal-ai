from datetime import date, datetime

from ninja import Schema

from parsifal.api.v1.schemas.common import OptionalDate


class ReviewOut(Schema):
    id: int
    name: str
    title: str
    description: str
    objective: str
    author: str
    co_authors: list[str]
    population: str
    intervention: str
    comparison: str
    outcome: str
    context: str
    review_type: str
    inclusion_rule: str  # all: a study must meet every inclusion criterion; any: at least one
    selection_procedure: str
    synthesis_strategy: str
    validity_threats: str
    quality_assessment_cutoff_score: float
    # The practical context of a rapid review (Cartaxo et al. 2020 §4.1)
    demand: str  # practitioners, agenda, prospected, organisation, other, or empty
    demand_notes: str
    practical_problem: str
    practical_context: str
    stakeholder_roles: str
    started_on: date | None = None
    deadline: date | None = None
    # The prefixes of the codes the review numbers its research questions, criteria, quality questions and extraction
    # fields with: {"question": "RQ", "inclusion": "IC", "exclusion": "EC", "quality": "QA", "extraction": "EX"}.
    code_prefixes: dict[str, str]
    create_date: datetime
    last_update: datetime

    @staticmethod
    def resolve_author(obj):
        return obj.author.username

    @staticmethod
    def resolve_code_prefixes(obj):
        from parsifal.apps.reviews.services import codes

        return codes.prefixes(obj)

    @staticmethod
    def resolve_co_authors(obj):
        return [user.username for user in obj.co_authors.all()]


class ReviewCreateIn(Schema):
    title: str
    description: str = ""
    review_type: str = "slr"  # slr, mapping or rapid


class ReviewUpdateIn(Schema):
    title: str | None = None
    description: str | None = None
    objective: str | None = None
    population: str | None = None
    intervention: str | None = None
    comparison: str | None = None
    outcome: str | None = None
    context: str | None = None
    review_type: str | None = None
    inclusion_rule: str | None = None  # all (every inclusion criterion) or any (at least one)
    selection_procedure: str | None = None
    synthesis_strategy: str | None = None
    validity_threats: str | None = None
    quality_assessment_cutoff_score: float | None = None
    demand: str | None = None
    demand_notes: str | None = None
    practical_problem: str | None = None
    practical_context: str | None = None
    stakeholder_roles: str | None = None
    started_on: OptionalDate = None
    deadline: OptionalDate = None
    # {"question": "QP", …} or ["question=QP", …]; a kind left out takes the default.
    code_prefixes: dict[str, str] | list[str] | None = None


class ReviewNameIn(Schema):
    name: str


class SelectionResetIn(Schema):
    reviewer_ids: list[int] = []  # delete these reviewers' decisions (every stage); the others keep theirs


class SelectionResetOut(Schema):
    unclassified: int  # studies that went back to unclassified (duplicates are kept)
    decisions_deleted: int
    runs_discarded: int  # the AI screening run in progress, if any


class AgentIn(Schema):
    name: str


class AgentOut(Schema):
    id: int  # the agent's user id
    name: str
    username: str
    created_at: datetime
    decisions: int
    quality_assessments: int
    data_extractions: int
    active_tokens: int


class AgentCreatedOut(AgentOut):
    token: str  # shown once; store it now


class ChangeOut(Schema):
    key: str = ""  # the field's name in the API, when it is one
    field: str
    before: str
    after: str


class ReviewEventOut(Schema):
    """One change to the review (its History)."""

    id: int
    created_at: datetime
    actor: str | None  # username; None for Parsifal itself or an account deleted since (see actor_name)
    actor_name: str
    via: str  # web, api, cli, mcp or system
    area: str  # review, planning, search, studies, selection, quality, extraction or analysis
    action: str  # add, change or remove
    summary: str
    subject: str
    subject_id: int | None
    changes: list[ChangeOut]
    items: list[str]
    article_ids: list[int]
    run_id: int | None
    amendment: bool  # a change to the protocol once studies were imported (PRISMA 2020 item 24c)

    @staticmethod
    def resolve_actor(obj):
        return obj.actor.username if obj.actor_id else None

    @staticmethod
    def resolve_article_ids(obj):
        return sorted(article.pk for article in obj.articles.all())


class ProgressStepOut(Schema):
    key: str
    label: str
    done: float  # 0 to 1
    detail: str


class ProgressPhaseOut(Schema):
    key: str
    label: str
    weight: int  # its share of the whole, in %
    percent: int
    steps: list[ProgressStepOut]


class ProgressOut(Schema):
    percent: int
    phases: list[ProgressPhaseOut]
    next: ProgressStepOut | None = None  # the first step not done


class WrittenCodeOut(Schema):
    key: str  # "question-12", "criteria-4", "quality-2", "extraction-9": what to give strip
    kind: str  # question, criteria, quality, extraction
    id: int
    code: str  # the code the review gives it now
    written: str  # the code typed in the name
    before: str
    after: str  # the name without it


class CodesOut(Schema):
    prefixes: dict[str, str]
    written: list[WrittenCodeOut]  # names that start with a code typed by hand


class CodesStripIn(Schema):
    keys: list[str] | None = None  # only these (see ``written``); left out: every one
