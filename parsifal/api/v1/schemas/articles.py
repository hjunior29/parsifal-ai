from datetime import datetime

from ninja import Schema

from parsifal.apps.accounts import services as integrations


class PdfOut(Schema):
    """The study's full text; download it from GET /reviews/{review_id}/articles/{article_id}/pdf."""

    filename: str
    content_type: str
    size: int
    sha256: str
    uploaded_by: str | None = None
    uploaded_at: datetime

    @staticmethod
    def resolve_uploaded_by(obj):
        return obj.uploaded_by.username if obj.uploaded_by else None

    @staticmethod
    def resolve_uploaded_at(obj):
        return obj.created_at


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
    pdf: PdfOut | None = None  # the full text, when one was uploaded
    starred: bool = False  # starred in this review (one mark per study, shared by every member)
    starred_by: str | None = None
    starred_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    updated_by: str | None = None
    # The study through your library proxy (Settings → Library access): its DOI, else its URL; null without one.
    access_url: str | None = None
    # How likely the study is relevant (0–1), by the latest AI run that answered about it: exclusion 1 − p(exclude),
    # inclusion the deciding criterion's p(meets), screen the lower of the two; null when no run did.
    ai_score: float | None = None

    @staticmethod
    def resolve_access_url(obj, context):
        request = (context or {}).get("request")
        if request is None:
            return None
        if not hasattr(request, "library_proxy"):  # once per request, however many studies are listed
            request.library_proxy = integrations.library_proxy_address(request.auth)
        return obj.access_url(request.library_proxy)

    @staticmethod
    def resolve_created_by(obj):
        return obj.created_by.username if obj.created_by else None

    @staticmethod
    def resolve_updated_by(obj):
        return obj.updated_by.username if obj.updated_by else None

    @staticmethod
    def resolve_starred_by(obj):
        return obj.starred_by.username if obj.starred_by else None

    @staticmethod
    def resolve_ai_score(obj):
        return obj.ai_score


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


class DuplicateGroupInfoOut(Schema):
    article_ids: list[int]
    match: str
    needs_review: bool
    reason: str


class DuplicateConflictOut(Schema):
    article_ids: list[int]
    reason: str


class DuplicateGroupsOut(Schema):
    groups: list[list[ArticleOut]]
    details: list[DuplicateGroupInfoOut] = []
    conflicts: list[DuplicateConflictOut] = []


class ResolveIn(Schema):
    ids: list[int] | None = None


class IdsIn(Schema):
    ids: list[int]


class ClearIn(Schema):
    source_id: int
    status: str | None = None
