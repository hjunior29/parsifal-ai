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


class ReviewUpdateIn(Schema):
    title: str | None = None
    description: str | None = None
    objective: str | None = None
    population: str | None = None
    intervention: str | None = None
    comparison: str | None = None
    outcome: str | None = None
    context: str | None = None
    quality_assessment_cutoff_score: float | None = None


class ReviewNameIn(Schema):
    name: str


class TransferIn(Schema):
    username: str


class MemberIn(Schema):
    username: str | None = None
    email: str | None = None
