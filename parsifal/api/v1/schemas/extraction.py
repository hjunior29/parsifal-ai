from typing import Any

from ninja import Schema

from parsifal.apps.reviews.services import extraction


class LookupOut(Schema):
    id: int
    value: str


class FieldOut(Schema):
    id: int
    description: str
    field_type: str
    order: int
    lookup_values: list[LookupOut]

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
    """``value`` for scalar and select-one fields (lookup id), ``values`` (lookup ids) for select-many fields."""

    field_id: int
    value: str | int | float | bool | None = None
    values: list[int] | None = None


class ExtractedValueOut(Schema):
    field_id: int
    field: str
    field_type: str
    value: Any = None


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

    @staticmethod
    def resolve_article_id(obj):
        return obj.pk

    @staticmethod
    def resolve_filled(obj):
        return extraction.filled(obj)
