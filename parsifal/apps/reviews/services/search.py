"""Conducting phase, search step: one adapted search string per digital library."""

from parsifal.apps.core.exceptions import NotFound
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
