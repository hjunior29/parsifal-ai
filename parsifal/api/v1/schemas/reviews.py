from datetime import datetime

from ninja import Schema


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
    create_date: datetime
    last_update: datetime

    @staticmethod
    def resolve_author(obj):
        return obj.author.username

    @staticmethod
    def resolve_co_authors(obj):
        return [user.username for user in obj.co_authors.all()]


class ReviewCreateIn(Schema):
    title: str
    description: str = ""
    review_type: str = "slr"


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
