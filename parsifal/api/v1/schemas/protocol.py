from datetime import date

from ninja import Schema

from parsifal.api.v1.schemas.common import OptionalDate


class QuestionOut(Schema):
    id: int
    question: str
    order: int
    parent_question_id: int | None = None


class QuestionIn(Schema):
    description: str
    parent_id: int | None = None


class QuestionUpdateIn(Schema):
    description: str


class KeywordOut(Schema):
    id: int
    description: str
    related_to: str
    synonyms: list[str]

    @staticmethod
    def resolve_synonyms(obj):
        return [synonym.description for synonym in obj.synonyms.all()]


class KeywordIn(Schema):
    description: str
    related_to: str = ""
    synonyms: list[str] = []


class KeywordUpdateIn(Schema):
    description: str | None = None
    related_to: str | None = None
    synonyms: list[str] | None = None


class SearchStringOut(Schema):
    search_string: str


class SearchStringIn(Schema):
    search_string: str


class SourceOut(Schema):
    id: int
    name: str
    url: str
    is_default: bool


class SourceAddIn(Schema):
    """Either ``source_id`` (a default digital library) or ``name``/``url`` (a custom source)."""

    source_id: int | None = None
    name: str | None = None
    url: str = ""


class SourceUpdateIn(Schema):
    name: str | None = None
    url: str | None = None


class SourceSearchStringOut(Schema):
    source_id: int
    source: str
    search_string: str
    search_type: str
    searched_at: date | None = None
    years_from: int | None = None
    years_to: int | None = None
    result_count: int | None = None

    @staticmethod
    def resolve_source(obj):
        return obj.source.name


class SourceSearchUpdateIn(Schema):
    """
    Search documentation (Kitchenham 6.1.4): how, when and how broadly the source was searched. Only the fields sent
    change; null (or "" for the date) clears the date, the years or the count.
    """

    search_type: str | None = None
    searched_at: OptionalDate = None
    years_from: int | None = None
    years_to: int | None = None
    result_count: int | None = None


class SourceImportOut(Schema):
    """A row of Import Studies: a source of the review, the studies imported from it and its date of search."""

    source_id: int
    source: str
    imported: int
    searched_at: date | None = None

    @staticmethod
    def resolve_source_id(obj):
        return obj.source.pk

    @staticmethod
    def resolve_source(obj):
        return obj.source.name


class CriteriaOut(Schema):
    id: int
    description: str
    criteria_type: str


class CriteriaIn(Schema):
    description: str
    criteria_type: str


class CriteriaUpdateIn(Schema):
    description: str
