"""Conducting phase, search step: one adapted search string per digital library."""

import datetime
from dataclasses import dataclass

from django.db.models import Count

from parsifal.apps.core.exceptions import NotFound, ValidationError
from parsifal.apps.reviews.models import SearchSession
from parsifal.apps.reviews.services._common import check_length, get_child, get_children


def list_source_search_strings(review):
    return review.searchsession_set.exclude(source=None).select_related("source").order_by("source__name")


def add_source_search_strings(*, review, source_ids):
    """Create empty search-string slots for the given review sources (ignoring the ones that exist)."""
    sources = get_children(review.sources, source_ids, label="Source")
    created = []
    for source in sources:
        session, was_created = SearchSession.objects.get_or_create(review=review, source=source)
        if was_created:
            created.append(session)
    return created


def set_source_search_string(*, review, source_id, search_string):
    source = get_child(review.sources, source_id, label="Source")
    check_length(search_string or "", 10000, field="search_string")
    session, _created = SearchSession.objects.update_or_create(
        review=review, source=source, defaults={"search_string": search_string or ""}
    )
    return session


def copy_generic_search_string(*, review, source_id):
    generic = review.searchsession_set.filter(source=None).first()
    search_string = generic.search_string if generic else ""
    return set_source_search_string(review=review, source_id=source_id, search_string=search_string)


def remove_source_search_string(*, review, source_id):
    source = get_child(review.sources, source_id, label="Source")
    deleted, _ = review.searchsession_set.filter(source=source).delete()
    if not deleted:
        raise NotFound(f"{source.name} has no search string in this review.")


def _parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        raise ValidationError("searched_at must be an ISO date (YYYY-MM-DD).", field="searched_at")


def _parse_int(value, field):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be an integer.", field=field)


SEARCH_FIELDS = ("search_type", "searched_at", "years_from", "years_to", "result_count")


def update_source_search(*, review, source_id, **changes):
    """
    Document a source search (Kitchenham 6.1.4; PRISMA 2020 item 6): how it was run, when, which years and how many
    results. Only the fields given change; None or "" clears the date, the years or the count. Creates the
    search-string slot when it does not exist yet.
    """
    unknown = set(changes) - set(SEARCH_FIELDS)
    if unknown:
        raise ValidationError(f"Unknown search fields: {sorted(unknown)}.")
    source = get_child(review.sources, source_id, label="Source")
    session, _created = SearchSession.objects.get_or_create(review=review, source=source)
    search_type = changes.get("search_type")
    if search_type is not None:
        if search_type not in dict(SearchSession.SEARCH_TYPES):
            raise ValidationError(f"search_type must be one of {[k for k, _ in SearchSession.SEARCH_TYPES]}.")
        session.search_type = search_type
    if "searched_at" in changes:
        session.searched_at = _parse_date(changes["searched_at"])
    for name in ("years_from", "years_to", "result_count"):
        if name in changes:
            setattr(session, name, _parse_int(changes[name], name))
    if session.years_from and session.years_to and session.years_from > session.years_to:
        raise ValidationError("years_from cannot be after years_to.", field="years_from")
    session.save()
    return session


@dataclass
class SourceImport:
    source: object
    imported: int
    searched_at: datetime.date | None


def list_source_imports(review):
    """The Import Studies table: each source of the review, the studies imported from it and its date of search."""
    counts = dict(
        review.article_set.order_by().values("source_id").annotate(count=Count("id")).values_list("source_id", "count")
    )
    dates = dict(review.searchsession_set.exclude(source=None).values_list("source_id", "searched_at"))
    return [
        SourceImport(source=source, imported=counts.get(source.pk, 0), searched_at=dates.get(source.pk))
        for source in review.sources.all()
    ]
