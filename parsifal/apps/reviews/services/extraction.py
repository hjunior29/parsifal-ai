"""Data extraction: form fields with lookup values and the per-article extracted values."""

from django.db import transaction

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import DataExtraction, DataExtractionField, DataExtractionLookup
from parsifal.apps.reviews.services._common import check_length, get_child, get_children, reorder, require

FIELD_TYPES = dict(DataExtractionField.FIELD_TYPES)


def _validate_field_type(field_type):
    if field_type not in FIELD_TYPES:
        raise ValidationError(f"field_type must be one of {sorted(FIELD_TYPES)}.", field="field_type")
    return field_type


def _clean_lookup_values(lookup_values):
    cleaned = []
    for value in lookup_values or ():
        value = (value or "").strip()
        if value and value not in cleaned:
            check_length(value, 1000, field="lookup_values")
            cleaned.append(value)
    return cleaned


@transaction.atomic
def add_field(*, review, description, field_type, lookup_values=()):
    require(description, field="description")
    check_length(description, 255, field="description")
    field = DataExtractionField.objects.create(
        review=review,
        description=description,
        field_type=_validate_field_type(field_type),
        order=review.dataextractionfield_set.count(),
    )
    _sync_lookups(field, lookup_values)
    return field


@transaction.atomic
def update_field(*, review, field_id, description=None, field_type=None, lookup_values=None):
    field = get_child(review.dataextractionfield_set, field_id, label="Data extraction field")
    if description is not None:
        require(description, field="description")
        field.description = check_length(description, 255, field="description")
    if field_type is not None and field_type != field.field_type:
        _validate_field_type(field_type)
        # Values recorded under the old type are meaningless for the new one.
        for extraction in field.dataextraction_set.all():
            extraction.value = ""
            extraction.select_values.clear()
            extraction.save(update_fields=["value"])
        field.field_type = field_type
    field.save()
    if lookup_values is not None or not field.is_select_field():
        _sync_lookups(field, lookup_values)
    return field


def _sync_lookups(field, lookup_values):
    if not field.is_select_field():
        field.dataextractionlookup_set.all().delete()
        return
    wanted = _clean_lookup_values(lookup_values)
    field.dataextractionlookup_set.exclude(value__in=wanted).delete()
    existing = set(field.dataextractionlookup_set.values_list("value", flat=True))
    for value in wanted:
        if value not in existing:
            DataExtractionLookup.objects.create(field=field, value=value)


def remove_field(*, review, field_id):
    get_child(review.dataextractionfield_set, field_id, label="Data extraction field").delete()


def reorder_fields(*, review, ordered_ids):
    return reorder(review.dataextractionfield_set, ordered_ids, label="Data extraction field")


def _get_article_and_field(review, article_id, field_id):
    article = get_child(review.article_set, article_id, label="Article")
    field = get_child(review.dataextractionfield_set, field_id, label="Data extraction field")
    return article, field


@transaction.atomic
def set_value(*, review, article_id, field_id, value=None, values=None, actor=None):
    """
    Set the extracted value of ``field`` for ``article``.

    ``value`` is a string for boolean/string/float/integer/date fields (coerced by the field type) or a
    lookup id for select-one fields; ``values`` is the full list of lookup ids for select-many fields
    (set semantics: the list replaces whatever was selected before).
    """
    article, field = _get_article_and_field(review, article_id, field_id)
    extraction, _created = DataExtraction.objects.get_or_create(article=article, field=field)
    extraction.user = actor
    if field.is_select_field():
        if field.field_type == DataExtractionField.SELECT_ONE_FIELD:
            ids = [value] if value not in (None, "") else []
        else:
            ids = list(values or [])
        lookups = get_children(field.dataextractionlookup_set, ids, label="Lookup value")
        extraction.value = ""
        extraction.save()
        extraction.select_values.set(lookups)
    else:
        try:
            extraction.set_value("" if value is None else str(value))
        except Exception as error:  # the model raises bare Exception/ValueError with a user-facing message
            raise ValidationError(str(error), field="value")
        extraction.save()
    return extraction


@transaction.atomic
def toggle_select_value(*, review, article_id, field_id, lookup_id, actor=None):
    """Legacy UI semantics for select-many fields: add the lookup if absent, remove it if present."""
    article, field = _get_article_and_field(review, article_id, field_id)
    if field.field_type != DataExtractionField.SELECT_MANY_FIELD:
        raise ValidationError("toggle is only valid for select-many fields.", field="field_id")
    lookup = get_child(field.dataextractionlookup_set, lookup_id, label="Lookup value")
    extraction, _created = DataExtraction.objects.get_or_create(article=article, field=field)
    extraction.user = actor
    extraction.value = ""
    extraction.save()
    if extraction.select_values.filter(pk=lookup.pk).exists():
        extraction.select_values.remove(lookup)
    else:
        extraction.select_values.add(lookup)
    return extraction


def mark_done(*, review, article_id, done=True):
    article = get_child(review.article_set, article_id, label="Article")
    article.finished_data_extraction = bool(done)
    article.save(update_fields=["finished_data_extraction", "updated_at"])
    return article


def article_values(*, review, article_id):
    """One entry per field of the review, with the typed value (or None) for the article."""
    article = get_child(review.article_set, article_id, label="Article")
    extractions = {e.field_id: e for e in article.dataextraction_set.prefetch_related("select_values")}
    rows = []
    for field in review.dataextractionfield_set.all():
        extraction = extractions.get(field.pk)
        rows.append({"field": field, "extraction": extraction, "value": serialize_value(field, extraction)})
    return rows


def serialize_value(field, extraction):
    """JSON-friendly value of an extraction: str/number/bool/date string, lookup value(s) or None."""
    if extraction is None:
        return None
    if field.field_type == DataExtractionField.SELECT_ONE_FIELD:
        lookup = extraction._get_select_one_value()
        return lookup.value if lookup else None
    if field.field_type == DataExtractionField.SELECT_MANY_FIELD:
        return list(extraction.select_values.values_list("value", flat=True))
    if field.field_type == DataExtractionField.DATE_FIELD:
        return extraction.value or None
    value = extraction.get_value()
    return None if value == "" else value
