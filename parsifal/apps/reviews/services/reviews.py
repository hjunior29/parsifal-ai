from django.contrib.auth.models import User
from django.db import transaction
from django.utils.text import slugify

from parsifal.apps.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from parsifal.apps.reviews.models import Review
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


def create_review(*, actor, title, description=""):
    require(title, field="title")
    check_length(title, 255, field="title")
    check_length(description, 500, field="description")
    return Review.objects.create(
        author=actor, title=title, description=description or "", name=unique_review_name(actor, title)
    )


def update_review(*, review, **fields):
    unknown = set(fields) - set(UPDATABLE_FIELDS)
    if unknown:
        raise ValidationError(f"Unknown review fields: {sorted(unknown)}.")
    for name, value in fields.items():
        limit = UPDATABLE_FIELDS[name]
        if name == "title":
            require(value, field="title")
        if name == "quality_assessment_cutoff_score":
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
    review.save()
    return review


def rename_review(*, review, name):
    require(name, field="name")
    check_length(name, 255, field="name")
    new_name = unique_review_name(review.author, name, exclude_pk=review.pk)
    if slugify(name) != name:
        raise ValidationError("Only letters, numbers, underscores or hyphens are allowed.", field="name")
    review.name = new_name
    review.save(update_fields=["name", "last_update"])
    return review


@transaction.atomic
def transfer_review(*, review, actor, to_user):
    require_owner(review, actor)
    if to_user == actor:
        raise ValidationError("You can't transfer the review to yourself.")
    if to_user in review.co_authors.all():
        review.co_authors.remove(to_user)
    review.author = to_user
    review.name = unique_review_name(to_user, review.name, exclude_pk=review.pk)
    review.save()
    review.co_authors.add(actor)
    return review


@transaction.atomic
def delete_review(*, review):
    for source in review.sources.all():
        if not source.is_default:
            review.sources.remove(source)
            source.delete()
    review.delete()


def add_co_author(*, review, user):
    if user == review.author:
        raise Conflict("The main author is already part of the review.")
    if review.co_authors.filter(pk=user.pk).exists():
        raise Conflict(f"{user.username} is already a co-author.")
    review.co_authors.add(user)
    return review


def remove_co_author(*, review, user):
    if not review.co_authors.filter(pk=user.pk).exists():
        raise NotFound(f"{user.username} is not a co-author of this review.")
    review.co_authors.remove(user)
    return review


def find_user_by_id(user_id):
    try:
        return User.objects.get(pk=user_id, is_active=True)
    except (User.DoesNotExist, ValueError, TypeError):
        raise NotFound(f"User {user_id} not found.")


def find_user(*, username=None, email=None):
    queryset = User.objects.filter(is_active=True)
    try:
        if username:
            return queryset.get(username__iexact=username)
        if email:
            return queryset.get(email__iexact=email)
    except User.DoesNotExist:
        pass
    raise NotFound("User not found.")


def review_overview(review):
    """Counts and prerequisites that agents need to decide what to do next."""
    articles = review.article_set
    accepted = review.get_accepted_articles().count()
    return {
        "id": review.pk,
        "name": review.name,
        "title": review.title,
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
