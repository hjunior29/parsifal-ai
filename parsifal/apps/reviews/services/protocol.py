"""Planning phase: research questions, keywords and synonyms, search string, sources, selection criteria."""

from django.db import transaction

from parsifal.apps.core.exceptions import Conflict, ValidationError
from parsifal.apps.reviews.models import Keyword, Question, ReviewEvent, SearchSession, SelectionCriteria, Source
from parsifal.apps.reviews.services import history
from parsifal.apps.reviews.services._common import check_length, get_child, get_children, reorder, require

PICOC_KEYWORD_SOURCES = (
    (Keyword.POPULATION, "population"),
    (Keyword.INTERVENTION, "intervention"),
    (Keyword.COMPARISON, "comparison"),
    (Keyword.OUTCOME, "outcome"),
)

# What the History records of each part of the protocol (the web views of Planning record the same).
QUESTION = history.Kind("research question", ReviewEvent.PLANNING, ("question",))
KEYWORD = history.Kind(
    "keyword", ReviewEvent.PLANNING, ("description", "related_to"), labels=(("related_to", "PICOC"),)
)
SOURCE = history.Kind("source", ReviewEvent.PLANNING, ("name", "url"), labels=(("url", "URL"),))
INCLUSION_CRITERION = history.Kind(
    "inclusion criterion", ReviewEvent.PLANNING, ("description",), plural="inclusion criteria"
)
EXCLUSION_CRITERION = history.Kind(
    "exclusion criterion", ReviewEvent.PLANNING, ("description",), plural="exclusion criteria"
)


def criterion_kind(criteria):
    return INCLUSION_CRITERION if criteria.criteria_type == SelectionCriteria.INCLUSION else EXCLUSION_CRITERION


def synonyms_of(keyword):
    return sorted(keyword.synonyms.values_list("description", flat=True))


def record_synonyms(review, keyword, tracker, before):
    """A keyword changed: its fields since ``tracker`` and its synonyms (``before``: as they were)."""
    after = synonyms_of(keyword)
    changes = [history.change("Synonyms", before, after, "synonyms")] if after != before else []
    return KEYWORD.changed(review, tracker, changes=changes)


def record_search_string(review, before, after):
    if (before or "") != (after or ""):
        history.record(
            review,
            ReviewEvent.PLANNING,
            history.CHANGED,
            "Changed the search string",
            subject="search_string",
            changes=[history.change("Search string", before, after, "search_string")],
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
    question = Question.objects.create(review=review, question=description, parent_question=parent, order=order)
    QUESTION.added(review, question)
    return question


def update_question(*, review, question_id, description):
    question = get_child(review.research_questions, question_id, label="Question")
    require(description, field="description")
    tracker = QUESTION.track(question)
    question.question = check_length(description, 500, field="description")
    question.save(update_fields=["question"])
    QUESTION.changed(review, tracker)
    return question


def remove_question(*, review, question_id):
    question = get_child(review.research_questions, question_id, label="Question")
    QUESTION.removed(review, question)
    question.delete()


def reorder_questions(*, review, ordered_ids):
    before = QUESTION.order(review.research_questions)
    questions = reorder(review.research_questions, ordered_ids, label="Question")
    QUESTION.reordered(review, review.research_questions, before)
    return questions


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
    added = synonyms_of(keyword)
    KEYWORD.added(review, keyword, changes=[history.change("Synonyms", "", added, "synonyms")] if added else ())
    return keyword


@transaction.atomic
def update_keyword(*, review, keyword_id, description=None, related_to=None, synonyms=None):
    keyword = get_child(review.keywords.filter(synonym_of=None), keyword_id, label="Keyword")
    tracker, before = KEYWORD.track(keyword), synonyms_of(keyword)
    if description is not None:
        require(description, field="description")
        keyword.description = check_length(description, 200, field="description")
    if related_to is not None:
        keyword.related_to = _validate_related_to(related_to)
    keyword.save()
    if synonyms is not None:
        _replace_synonyms(keyword, synonyms)
    record_synonyms(review, keyword, tracker, before)
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


def record_keyword_removed(review, keyword):
    if keyword.synonym_of_id:
        KEYWORD.changed(
            review,
            KEYWORD.track(keyword.synonym_of),
            changes=[history.change("Synonym removed", keyword.description, "", "synonyms")],
        )
    else:
        synonyms = synonyms_of(keyword)
        KEYWORD.removed(
            review, keyword, changes=[history.change("Synonyms", synonyms, "", "synonyms")] if synonyms else ()
        )


def remove_keyword(*, review, keyword_id):
    keyword = get_child(review.keywords, keyword_id, label="Keyword")
    record_keyword_removed(review, keyword)
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
    record_picoc_keywords(review, created)
    return created


def record_picoc_keywords(review, keywords):
    if keywords:
        history.record(
            review,
            ReviewEvent.PLANNING,
            history.ADDED,
            f"Added {history.plural(len(keywords), 'keyword')} from the PICOC",
            subject="keyword",
            items=[f"{keyword.description} ({keyword.get_related_to_display()})" for keyword in keywords],
        )


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
    before = getattr(get_generic_search_string(review), "search_string", "")
    session, _created = SearchSession.objects.update_or_create(
        review=review, source=None, defaults={"search_string": search_string or ""}
    )
    record_search_string(review, before, session.search_string)
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
    SOURCE.added(review, source)
    return source


def create_source(*, review, name, url=""):
    require(name, field="name")
    check_length(name, 100, field="name")
    check_length(url or "", 200, field="url")
    source = Source(name=name)
    source.set_url(url or "")
    source.save()
    review.sources.add(source)
    SOURCE.added(review, source)
    return source


def update_source(*, review, source_id, name=None, url=None):
    source = get_child(review.sources, source_id, label="Source")
    if source.is_default:
        raise ValidationError("Default digital libraries cannot be edited.")
    tracker = SOURCE.track(source)
    if name is not None:
        require(name, field="name")
        source.name = check_length(name, 100, field="name")
    if url is not None:
        check_length(url, 200, field="url")
        source.set_url(url)
    source.save()
    SOURCE.changed(review, tracker)
    return source


@transaction.atomic
def detach_source(*, review, source_id):
    """
    Detach a source. Default libraries are shared, so the review's articles and search string from it are
    deleted; custom sources belong to the review and are deleted outright.
    """
    source = get_child(review.sources, source_id, label="Source")
    studies = review.article_set.filter(source=source)
    titles = list(studies.order_by("title").values_list("title", flat=True))
    suffix = f" and its {history.studies(len(titles))}" if titles else ""
    SOURCE.removed(review, source, suffix=suffix, items=titles)
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
    criteria = SelectionCriteria.objects.create(
        review=review,
        description=description,
        criteria_type=criteria_type,
        order=review.selectioncriteria_set.filter(criteria_type=criteria_type).count(),
    )
    criterion_kind(criteria).added(review, criteria)
    return criteria


def update_criteria(*, review, criteria_id, description):
    criteria = get_child(review.selectioncriteria_set, criteria_id, label="Selection criteria")
    require(description, field="description")
    tracker = criterion_kind(criteria).track(criteria)
    criteria.description = check_length(description, 200, field="description")
    criteria.save(update_fields=["description"])
    criterion_kind(criteria).changed(review, tracker)
    return criteria


def remove_criteria(*, review, criteria_id):
    criteria = get_child(review.selectioncriteria_set, criteria_id, label="Selection criteria")
    criterion_kind(criteria).removed(review, criteria)
    criteria.delete()


def reorder_criteria(*, review, ordered_ids):
    """
    The order of the inclusion criteria, or of the exclusion ones (``ordered_ids``, all of one type): it gives them
    their codes (IC1, IC2…; EC1…).
    """
    found = get_children(review.selectioncriteria_set, ordered_ids, label="Selection criteria")
    types = {criteria.criteria_type for criteria in found}
    if len(types) != 1:
        raise ValidationError("Reorder the inclusion criteria or the exclusion criteria, one type at a time.")
    queryset = review.selectioncriteria_set.filter(criteria_type=types.pop())
    kind = criterion_kind(found[0])
    before = kind.order(queryset)
    criteria = reorder(queryset, ordered_ids, label="Selection criteria")
    kind.reordered(review, queryset, before)
    return criteria
