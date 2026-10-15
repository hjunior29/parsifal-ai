from typing import Any

from ninja import Schema


class FacetTemplateOut(Schema):
    key: str
    name: str
    description: str
    multiple: bool
    categories: list[str]


class CategoryOut(Schema):
    id: int
    name: str
    description: str
    order: int


class FacetOut(Schema):
    id: int
    name: str
    description: str
    kind: str
    template: str
    multiple: bool
    order: int
    categories: list[CategoryOut]

    @staticmethod
    def resolve_categories(obj):
        return list(obj.categories.all())


class FacetIn(Schema):
    """Either ``template`` (research_type, contribution_type, research_method, venue_type, study_focus) or a custom
    facet with ``name`` and optional ``categories``."""

    template: str | None = None
    name: str | None = None
    description: str = ""
    kind: str = "emerging"
    multiple: bool = False
    categories: list[str] = []


class FacetUpdateIn(Schema):
    name: str | None = None
    description: str | None = None
    kind: str | None = None
    multiple: bool | None = None


class CategoryIn(Schema):
    name: str
    description: str = ""


class CategoryUpdateIn(Schema):
    name: str | None = None
    description: str | None = None


class ClassificationIn(Schema):
    facet_id: int
    category_ids: list[int] = []
    notes: str = ""


class FacetClassificationOut(Schema):
    facet_id: int
    facet: str
    multiple: bool
    category_ids: list[int]
    categories: list[str]
    notes: str
    user: str | None = None


class ArticleClassificationOut(Schema):
    article_id: int
    facets: list[FacetClassificationOut]


class FacetFrequenciesOut(Schema):
    facet_id: int
    facet: str
    total_articles: int
    classified_articles: int
    categories: list[dict[str, Any]]


class FacetMatrixOut(Schema):
    rows: dict[str, Any]
    columns: dict[str, Any]
    cells: list[dict[str, Any]]


class TestSetItemOut(Schema):
    id: int
    title: str
    doi: str
    notes: str
    matched_article_id: int | None = None


class TestSetItemIn(Schema):
    title: str
    doi: str = ""
    notes: str = ""


class TestSetItemUpdateIn(Schema):
    title: str | None = None
    doi: str | None = None
    notes: str | None = None


class TestSetReportOut(Schema):
    total: int
    found: int
    recall: float | None = None
    items: list[TestSetItemOut]


class ChecklistItemOut(Schema):
    key: str
    phase: str
    label: str
    applied: bool
    notes: str


class ChecklistOut(Schema):
    applied: int
    total: int
    ratio: float
    items: list[ChecklistItemOut]


class ChecklistItemIn(Schema):
    applied: bool
    notes: str | None = None
