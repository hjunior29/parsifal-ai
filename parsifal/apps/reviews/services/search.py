"""Conducting phase, search step: one adapted search string per digital library."""

import datetime

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


def update_source_search(
    *, review, source_id, search_type=None, searched_at=None, years_from=None, years_to=None, result_count=None
):
    """
    Document a source search (Kitchenham 6.1.4): how it was run, when, which years and how many results.
    Creates the search-string slot when it does not exist yet.
    """
    source = get_child(review.sources, source_id, label="Source")
    session, _created = SearchSession.objects.get_or_create(review=review, source=source)
    if search_type is not None:
        if search_type not in dict(SearchSession.SEARCH_TYPES):
            raise ValidationError(f"search_type must be one of {[k for k, _ in SearchSession.SEARCH_TYPES]}.")
        session.search_type = search_type
    if searched_at is not None:
        session.searched_at = _parse_date(searched_at)
    if years_from is not None:
        session.years_from = _parse_int(years_from, "years_from")
    if years_to is not None:
        session.years_to = _parse_int(years_to, "years_to")
    if session.years_from and session.years_to and session.years_from > session.years_to:
        raise ValidationError("years_from cannot be after years_to.", field="years_from")
    if result_count is not None:
        session.result_count = _parse_int(result_count, "result_count")
    session.save()
    return session
