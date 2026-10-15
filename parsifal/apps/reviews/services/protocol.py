"""Planning phase: research questions, keywords and synonyms, search string, sources, selection criteria."""

from django.db import transaction

from parsifal.apps.core.exceptions import Conflict, ValidationError
from parsifal.apps.reviews.models import Keyword, Question, SearchSession, SelectionCriteria, Source
from parsifal.apps.reviews.services._common import check_length, get_child, reorder, require

PICOC_KEYWORD_SOURCES = (
    (Keyword.POPULATION, "population"),
    (Keyword.INTERVENTION, "intervention"),
    (Keyword.COMPARISON, "comparison"),
    (Keyword.OUTCOME, "outcome"),
)


# ---------------------------------------------------------------------------------------------------------------------
# Research questions
# ---------------------------------------------------------------------------------------------------------------------


def add_question(*, review, description, parent_id=None):
    require(description, field="description")
    check_length(description, 500, field="description")
    parent = None
    if parent_id is not None:
        parent = get_child(review.research_questions, parent_id, label="Question")
    order = review.research_questions.count()
    return Question.objects.create(review=review, question=description, parent_question=parent, order=order)


def update_question(*, review, question_id, description):
    question = get_child(review.research_questions, question_id, label="Question")
    require(description, field="description")
    question.question = check_length(description, 500, field="description")
    question.save(update_fields=["question"])
    return question


def remove_question(*, review, question_id):
    get_child(review.research_questions, question_id, label="Question").delete()


def reorder_questions(*, review, ordered_ids):
    return reorder(review.research_questions, ordered_ids, label="Question")


# ---------------------------------------------------------------------------------------------------------------------
# Keywords and synonyms
# ---------------------------------------------------------------------------------------------------------------------


def _validate_related_to(related_to):
    related_to = related_to or ""
    if related_to not in dict(Keyword.RELATED_TO) and related_to != "":
        raise ValidationError(f"related_to must be one of {[k for k, _ in Keyword.RELATED_TO]} or empty.")
    return related_to


@transaction.atomic
def add_keyword(*, review, description, related_to="", synonyms=()):
    require(description, field="description")
    check_length(description, 200, field="description")
    keyword = Keyword.objects.create(
        review=review, description=description, related_to=_validate_related_to(related_to)
    )
    _replace_synonyms(keyword, synonyms)
    return keyword


@transaction.atomic
def update_keyword(*, review, keyword_id, description=None, related_to=None, synonyms=None):
    keyword = get_child(review.keywords.filter(synonym_of=None), keyword_id, label="Keyword")
    if description is not None:
        require(description, field="description")
        keyword.description = check_length(description, 200, field="description")
    if related_to is not None:
        keyword.related_to = _validate_related_to(related_to)
    keyword.save()
    if synonyms is not None:
        _replace_synonyms(keyword, synonyms)
    return keyword


def _replace_synonyms(keyword, synonyms):
    keyword.synonyms.all().delete()
    for synonym in synonyms:
        synonym = (synonym or "").strip()
        if synonym:
            check_length(synonym, 200, field="synonym")
            Keyword.objects.create(
                review=keyword.review, description=synonym, synonym_of=keyword, related_to=keyword.related_to
            )


def remove_keyword(*, review, keyword_id):
    keyword = get_child(review.keywords, keyword_id, label="Keyword")
    keyword.synonyms.all().delete()
    keyword.delete()


def import_picoc_keywords(*, review):
    """Create top-level keywords from the comma-separated PICO fields; returns the keywords created."""
    existing = set(review.keywords.filter(synonym_of=None).values_list("description", flat=True))
    created = []
    for related_to, field in PICOC_KEYWORD_SOURCES:
        for term in (getattr(review, field) or "").split(","):
            term = term.strip()
            if term and term not in existing:
                created.append(Keyword.objects.create(review=review, description=term, related_to=related_to))
                existing.add(term)
    return created


def generate_search_string(review):
    """``("k1" OR "s1") AND ("k2" OR "s2")`` — one group per PICO category that has keywords."""
    groups = []
    for key, _label in Keyword.RELATED_TO:
        terms = []
        for keyword in review.keywords.filter(related_to=key, synonym_of=None):
            terms.append(f'"{keyword.description}"')
            terms.extend(f'"{synonym.description}"' for synonym in keyword.synonyms.all())
        if terms:
            groups.append("({0})".format(" OR ".join(terms)))
    return " AND ".join(groups)


# ---------------------------------------------------------------------------------------------------------------------
# Generic search string
# ---------------------------------------------------------------------------------------------------------------------


def get_generic_search_string(review):
    return review.searchsession_set.filter(source=None).first()


def set_generic_search_string(*, review, search_string):
    check_length(search_string or "", 10000, field="search_string")
    session, _created = SearchSession.objects.update_or_create(
        review=review, source=None, defaults={"search_string": search_string or ""}
    )
    return session


# ---------------------------------------------------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------------------------------------------------


def list_default_sources():
    return Source.objects.filter(is_default=True)


def attach_source(*, review, source_id):
    """Attach an existing (default) digital library to the review."""
    source = get_child(Source.objects.filter(is_default=True), source_id, label="Default source")
    if review.sources.filter(pk=source.pk).exists():
        raise Conflict(f"{source.name} is already attached to this review.")
    review.sources.add(source)
    return source


def create_source(*, review, name, url=""):
    require(name, field="name")
    check_length(name, 100, field="name")
    check_length(url or "", 200, field="url")
    source = Source(name=name)
    source.set_url(url or "")
    source.save()
    review.sources.add(source)
    return source


def update_source(*, review, source_id, name=None, url=None):
    source = get_child(review.sources, source_id, label="Source")
    if source.is_default:
        raise ValidationError("Default digital libraries cannot be edited.")
    if name is not None:
        require(name, field="name")
        source.name = check_length(name, 100, field="name")
    if url is not None:
        check_length(url, 200, field="url")
        source.set_url(url)
    source.save()
    return source


@transaction.atomic
def detach_source(*, review, source_id):
    """
    Detach a source. Default libraries are shared, so the review's articles and search string from it are
    deleted; custom sources belong to the review and are deleted outright.
    """
    source = get_child(review.sources, source_id, label="Source")
    review.sources.remove(source)
    review.searchsession_set.filter(source=source).delete()
    if source.is_default:
        review.article_set.filter(source=source).delete()
    else:
        source.delete()
    review.save()


# ---------------------------------------------------------------------------------------------------------------------
# Selection criteria
# ---------------------------------------------------------------------------------------------------------------------


def add_criteria(*, review, description, criteria_type):
    require(description, field="description")
    check_length(description, 200, field="description")
    if criteria_type not in dict(SelectionCriteria.SELECTION_TYPES):
        raise ValidationError("criteria_type must be 'I' (inclusion) or 'E' (exclusion).", field="criteria_type")
    return SelectionCriteria.objects.create(review=review, description=description, criteria_type=criteria_type)


def update_criteria(*, review, criteria_id, description):
    criteria = get_child(review.selectioncriteria_set, criteria_id, label="Selection criteria")
    require(description, field="description")
    criteria.description = check_length(description, 200, field="description")
    criteria.save(update_fields=["description"])
    return criteria


def remove_criteria(*, review, criteria_id):
    get_child(review.selectioncriteria_set, criteria_id, label="Selection criteria").delete()
