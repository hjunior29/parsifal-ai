import datetime

from django.db import transaction
from django.utils.text import slugify

from parsifal.apps.core.exceptions import NotFound, PermissionDenied, ValidationError
from parsifal.apps.reviews.models import Review, ReviewEvent
from parsifal.apps.reviews.services import history
from parsifal.apps.reviews.services._common import check_length, require

DEFAULT_NAME = "literature-review"

# Fields that update_review accepts, with their maximum lengths (None = not a text field).
UPDATABLE_FIELDS = {
    "title": 255,
    "description": 500,
    "objective": 1000,
    "population": 200,
    "intervention": 200,
    "comparison": 200,
    "outcome": 200,
    "context": 200,
    "quality_assessment_cutoff_score": None,
    "review_type": None,
    "inclusion_rule": None,
    "selection_procedure": 10000,
    "synthesis_strategy": 10000,
    "validity_threats": 10000,
    # The practical context of a rapid review (Cartaxo et al. 2020 §4.1)
    "demand": None,
    "demand_notes": 4000,
    "practical_problem": 4000,
    "practical_context": 4000,
    "stakeholder_roles": 4000,
    "started_on": None,
    "deadline": None,
    "code_prefixes": None,
}
DATE_FIELDS = ("started_on", "deadline")

# Where each field of the review is changed, for the History; the others are the protocol's (Planning).
REVIEW_FIELD_AREAS = {
    "name": ReviewEvent.REVIEW,
    "title": ReviewEvent.REVIEW,
    "description": ReviewEvent.REVIEW,
    "review_type": ReviewEvent.REVIEW,
    "code_prefixes": ReviewEvent.REVIEW,
    "status": ReviewEvent.REVIEW,
    "prisma_not_retrieved": ReviewEvent.ANALYSIS,
}
AREA_SUMMARIES = {
    ReviewEvent.REVIEW: "Changed the review details",
    ReviewEvent.PLANNING: "Changed the protocol",
    ReviewEvent.ANALYSIS: "Changed the PRISMA flow diagram settings",
}


def require_member(review, user):
    if not review.is_author_or_coauthor(user):
        raise PermissionDenied("You are not an author of this review.")
    return review


def require_owner(review, user):
    if review.author_id != user.id:
        raise PermissionDenied("Only the main author can do this.")
    return review


def get_review(*, author_username, name):
    try:
        return Review.objects.select_related("author__profile").get(
            author__username__iexact=author_username, name=name
        )
    except Review.DoesNotExist:
        raise NotFound(f"Review {author_username}/{name} not found.")


def unique_review_name(author, base, *, exclude_pk=None):
    """Return ``base`` or ``base-N`` so that (name, author) is unique."""
    base = slugify(base) or DEFAULT_NAME
    queryset = Review.objects.filter(author=author)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    candidate = base
    i = 0
    while queryset.filter(name=candidate).exists():
        i += 1
        candidate = f"{base}-{i}"
    return candidate


def track_review(review, *fields):
    """The review's fields as they are now (all that people change when none is given), for ``record_changes``."""
    return history.track(review, *(fields or (*UPDATABLE_FIELDS, "name", "status")))


def record_changes(review, tracker):
    """One event per area for what changed in the review since ``tracker`` (see ``track_review``)."""
    by_area = {}
    for change in tracker.changes():
        area = REVIEW_FIELD_AREAS.get(change["key"], ReviewEvent.PLANNING)
        by_area.setdefault(area, []).append(change)
    for area, changes in by_area.items():
        fields = ", ".join(change["field"] for change in changes)
        history.record(
            review, area, history.CHANGED, f"{AREA_SUMMARIES[area]} ({fields})", subject="review", changes=changes
        )


def record_created(review, actor=None, summary="Created the review"):
    history.record(review, ReviewEvent.REVIEW, history.ADDED, f"{summary} {history.quote(review.title)}", actor=actor)


def create_review(*, actor, title, description=""):
    require(title, field="title")
    check_length(title, 255, field="title")
    check_length(description, 500, field="description")
    review = Review.objects.create(
        author=actor, title=title, description=description or "", name=unique_review_name(actor, title)
    )
    record_created(review, actor)
    return review


def update_review(*, review, **fields):
    unknown = set(fields) - set(UPDATABLE_FIELDS)
    if unknown:
        raise ValidationError(f"Unknown review fields: {sorted(unknown)}.")
    tracker = track_review(review, *fields)
    for name, value in fields.items():
        limit = UPDATABLE_FIELDS[name]
        if name == "title":
            require(value, field="title")
        if name == "review_type":
            value = _review_type(review, value)
        elif name == "demand":
            if value and value not in dict(Review.DEMANDS):
                raise ValidationError(f"demand must be one of {_keys(Review.DEMANDS)}, or empty.", field=name)
            value = value or ""
        elif name in DATE_FIELDS:
            value = _date(value, name)
        elif name == "code_prefixes":
            from parsifal.apps.reviews.services import codes  # it imports the models this module does

            value = codes.clean_prefixes(value, codes.prefixes(review))
        elif name == "inclusion_rule":
            if value not in dict(Review.INCLUSION_RULES):
                raise ValidationError(
                    "inclusion_rule must be 'all' (a study meets every inclusion criterion) or 'any' (at least one).",
                    field=name,
                )
        elif name == "quality_assessment_cutoff_score":
            if isinstance(value, str):
                value = value.replace(",", ".")
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValidationError("Cutoff score must be a number.", field=name)
            if value < 0:
                raise ValidationError("Cutoff score cannot be negative.", field=name)
        elif limit is not None:
            value = check_length(value or "", limit, field=name)
        setattr(review, name, value)
    if review.started_on and review.deadline and review.deadline < review.started_on:
        raise ValidationError("The deadline cannot come before the start date.", field="deadline")
    review.save()
    record_changes(review, tracker)
    return review


def _keys(choices):
    return ", ".join(f"'{key}'" for key, _label in choices)


def _review_type(review, value):
    if value not in dict(Review.REVIEW_TYPES):
        raise ValidationError(f"review_type must be one of {_keys(Review.REVIEW_TYPES)}.", field="review_type")
    check_type_change(review, value)
    return value


def check_type_change(review, review_type):
    """
    A rapid review stays one while it has decisions at the title round, which the other types do not have. Its
    practical context and checklist are kept when the type changes, only not shown.
    """
    from parsifal.apps.reviews.models import StudyDecision

    if (
        review.is_rapid_review
        and review_type != Review.RAPID
        and review.decisions.filter(stage=StudyDecision.TITLE).exists()
    ):
        raise ValidationError(
            "This rapid review has decisions at the title round, which other types of review do not have: remove "
            "them (or reset the study selection) before changing its type.",
            field="review_type",
        )


def _date(value, field):
    if value in (None, ""):
        return None
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        raise ValidationError(f"{field} must be a date (YYYY-MM-DD).", field=field)


def rename_review(*, review, name):
    require(name, field="name")
    check_length(name, 255, field="name")
    new_name = unique_review_name(review.author, name, exclude_pk=review.pk)
    if slugify(name) != name:
        raise ValidationError("Only letters, numbers, underscores or hyphens are allowed.", field="name")
    tracker = track_review(review, "name")
    review.name = new_name
    review.save(update_fields=["name", "last_update"])
    record_changes(review, tracker)
    return review


@transaction.atomic
def delete_review(*, review):
    for source in review.sources.all():
        if not source.is_default:
            review.sources.remove(source)
            source.delete()
    review.delete()


def review_overview(review):
    """Counts and prerequisites that agents need to decide what to do next."""
    articles = review.article_set
    accepted = review.get_accepted_articles().count()
    from parsifal.apps.reviews.services import decisions, mapping

    return {
        "id": review.pk,
        "name": review.name,
        "title": review.title,
        "review_type": review.review_type,
        "author": review.author.username,
        "co_authors": list(review.co_authors.values_list("username", flat=True)),
        "sources": review.sources.count(),
        "research_questions": review.research_questions.count(),
        "keywords": review.keywords.filter(synonym_of=None).count(),
        "selection_criteria": review.selectioncriteria_set.count(),
        "has_generic_search_string": review.searchsession_set.filter(source=None).exclude(search_string="").exists(),
        "quality_questions": review.qualityquestion_set.count(),
        "quality_answers": review.qualityanswer_set.count(),
        "quality_assessment_cutoff_score": review.quality_assessment_cutoff_score,
        "data_extraction_fields": review.dataextractionfield_set.count(),
        "test_set": {
            "total": review.test_set.count(),
            "found": review.test_set.filter(matched_article__isnull=False).count(),
        },
        "process_checklist_ratio": mapping.checklist(review)["ratio"],
        "decisions": decisions.summary(review),
        "articles": {
            "total": articles.count(),
            "unclassified": articles.filter(status="U").count(),
            "accepted": accepted,
            "rejected": articles.filter(status="R").count(),
            "duplicated": articles.filter(status="D").count(),
            "final_selection": review.get_final_selection_articles().count(),
            "extraction_done": articles.filter(status="A", finished_data_extraction=True).count(),
        },
    }
