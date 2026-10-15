from datetime import datetime

from ninja import Schema


class ArticleOut(Schema):
    id: int
    bibtex_key: str
    title: str | None = None
    author: str | None = None
    journal: str | None = None
    year: str | None = None
    year_int: int | None = None
    source_id: int | None = None
    pages: str | None = None
    volume: str | None = None
    abstract: str | None = None
    document_type: str | None = None
    doi: str | None = None
    url: str | None = None
    affiliation: str | None = None
    author_keywords: str | None = None
    keywords: str | None = None
    publisher: str | None = None
    issn: str | None = None
    language: str | None = None
    note: str | None = None
    status: str
    selection_criteria_id: int | None = None
    found_via_id: int | None = None
    comments: str | None = None
    finished_data_extraction: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    updated_by: str | None = None

    @staticmethod
    def resolve_created_by(obj):
        return obj.created_by.username if obj.created_by else None

    @staticmethod
    def resolve_updated_by(obj):
        return obj.updated_by.username if obj.updated_by else None


class ArticleFieldsIn(Schema):
    bibtex_key: str | None = None
    title: str | None = None
    author: str | None = None
    journal: str | None = None
    year: str | None = None
    pages: str | None = None
    volume: str | None = None
    abstract: str | None = None
    document_type: str | None = None
    doi: str | None = None
    url: str | None = None
    affiliation: str | None = None
    author_keywords: str | None = None
    keywords: str | None = None
    publisher: str | None = None
    issn: str | None = None
    language: str | None = None
    note: str | None = None
    comments: str | None = None


class ArticleCreateIn(ArticleFieldsIn):
    source_id: int
    status: str | None = None
    selection_criteria_id: int | None = None


class ArticleUpdateIn(ArticleFieldsIn):
    status: str | None = None
    selection_criteria_id: int | None = None


class StatusIn(Schema):
    ids: list[int]
    status: str
    selection_criteria_id: int | None = None
    comments: str | None = None


class ImportIn(Schema):
    source_id: int
    bibtex: str


class ImportOut(Schema):
    imported: int
    failed: int
    warnings: list[str]
    article_ids: list[int]


class DuplicateGroupsOut(Schema):
    groups: list[list[ArticleOut]]


class ResolveIn(Schema):
    ids: list[int] | None = None
