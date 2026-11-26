from typing import Any

from ninja import Schema

from parsifal.api.v1.schemas.common import resolve_code
from parsifal.apps.reviews.services import extraction


class LookupOut(Schema):
    id: int
    value: str


class FieldOut(Schema):
    id: int
    code: str  # the review's: EX1, EX2… (from the order)
    description: str
    field_type: str
    order: int
    lookup_values: list[LookupOut]

    resolve_code = staticmethod(resolve_code)

    @staticmethod
    def resolve_lookup_values(obj):
        return list(obj.dataextractionlookup_set.all())


class FieldIn(Schema):
    description: str
    field_type: str
    lookup_values: list[str] = []


class FieldUpdateIn(Schema):
    description: str | None = None
    field_type: str | None = None
    lookup_values: list[str] | None = None


class ValueIn(Schema):
    """
    ``value`` for scalar and select-one fields (lookup id), ``values`` (lookup ids) for select-many fields;
    ``evidence``: where the study supports the value (left as it is when not given).
    """

    field_id: int
    value: str | int | float | bool | None = None
    values: list[int] | None = None
    evidence: str | None = None


class EvidenceIn(Schema):
    """Where the study supports the value of the field: the passage, its page, the figure or table."""

    field_id: int
    evidence: str


class ExtractedValueOut(Schema):
    field_id: int
    code: str = ""  # the field's
    field: str
    field_type: str
    value: Any = None
    evidence: str = ""
    needs_evidence: bool = False  # it has a value but no evidence


class ArticleExtractionOut(Schema):
    article_id: int
    finished_data_extraction: bool
    values: list[ExtractedValueOut]


class DoneIn(Schema):
    done: bool = True


class ExtractionStudyOut(Schema):
    """A study of Data Extraction's list."""

    article_id: int
    title: str
    year: str | None = None
    score: float  # its quality score
    finished_data_extraction: bool
    filled: int  # fields with a value
    without_evidence: int  # of those, the ones with no evidence

    @staticmethod
    def resolve_article_id(obj):
        return obj.pk

    @staticmethod
    def resolve_filled(obj):
        return extraction.filled(obj)

    @staticmethod
    def resolve_without_evidence(obj):
        return extraction.without_evidence(obj)
