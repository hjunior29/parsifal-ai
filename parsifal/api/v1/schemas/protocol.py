from datetime import date

from ninja import Schema


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
    """Search documentation (Kitchenham 6.1.4): how, when and how broadly the source was searched."""

    search_type: str | None = None
    searched_at: date | None = None
    years_from: int | None = None
    years_to: int | None = None
    result_count: int | None = None


class CriteriaOut(Schema):
    id: int
    description: str
    criteria_type: str


class CriteriaIn(Schema):
    description: str
    criteria_type: str


class CriteriaUpdateIn(Schema):
    description: str
