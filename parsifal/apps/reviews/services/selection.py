"""
Study selection as a whole: going back to its start, to screen again (for instance with another request to Jev)
without the earlier classifications and decisions getting in the way. The log of the AI screening runs is kept.
"""

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from parsifal.apps.core.exceptions import NotFound, PermissionDenied, ValidationError
from parsifal.apps.reviews.models import Article, ReviewAgent, ScreeningRun
from parsifal.apps.reviews.services import ai_screening

DISCARDED = "Discarded: the study selection was reset."


def _classified(review):
    """What a reset changes: studies accepted or rejected, and unclassified ones left with a criterion."""
    return review.article_set.filter(
        Q(status__in=(Article.ACCEPTED, Article.REJECTED))
        | Q(status=Article.UNCLASSIFIED, selection_criteria__isnull=False)
    )


def reset_summary(review):
    """
    What a reset would change and keep: studies per status (and how many would change), the reviewers with
    decisions (how many, and whether each is an AI agent), the AI runs and whether one is in progress.
    """
    counts = dict(review.article_set.order_by().values_list("status").annotate(n=Count("pk")))
    decisions = dict(review.decisions.order_by().values_list("user_id").annotate(n=Count("pk")))
    agents = set(ReviewAgent.objects.filter(review=review).values_list("user_id", flat=True))
    return {
        "accepted": counts.get(Article.ACCEPTED, 0),
        "rejected": counts.get(Article.REJECTED, 0),
        "unclassified": counts.get(Article.UNCLASSIFIED, 0),
        "duplicated": counts.get(Article.DUPLICATED, 0),
        "to_unclassify": _classified(review).count(),
        "reviewers": [
            {"user": user, "decisions": decisions[user.pk], "is_agent": user.pk in agents}
            for user in User.objects.filter(pk__in=decisions).select_related("profile").order_by("username")
        ],
        "runs": review.screening_runs.count(),
        "running_run": review.screening_runs.filter(status=ScreeningRun.RUNNING).exists(),
    }


def _clean_reviewer_ids(review, reviewer_ids):
    if reviewer_ids in (None, ""):
        return set()
    if isinstance(reviewer_ids, (str, int)):
        reviewer_ids = [reviewer_ids]
    try:
        ids = {int(value) for value in reviewer_ids if str(value).strip()}
    except (TypeError, ValueError):
        raise ValidationError("reviewer_ids must be user ids.", field="reviewer_ids")
    known = set(review.decisions.values_list("user_id", flat=True))
    known |= {review.author_id, *review.co_authors.values_list("pk", flat=True)}
    unknown = sorted(ids - known)
    if unknown:
        raise NotFound(f"Reviewer {unknown} is not in this review.", field="reviewer_ids")
    return ids


@transaction.atomic
def reset(*, review, actor, reviewer_ids=()):
    """
    Back to the start of study selection: every study that is not a duplicate becomes unclassified, without a
    criterion (``actor`` is its last editor); the decisions of ``reviewer_ids`` are deleted, at every stage; a run
    of Exclude/Include with AI in progress is discarded. Kept: duplicates, the other reviewers' decisions, the log of
    the AI runs (with their requests to Jev), stars, PDFs, quality assessments and extracted data. Only the main
    author; it cannot be undone. Returns {"unclassified", "decisions_deleted", "runs_discarded"}.
    """
    if actor.pk != review.author_id:
        raise PermissionDenied("Only the main author can reset the study selection.")
    ids = _clean_reviewer_ids(review, reviewer_ids)
    unclassified = _classified(review).update(
        status=Article.UNCLASSIFIED, selection_criteria=None, updated_by=actor, updated_at=timezone.now()
    )
    decisions = review.decisions.filter(user_id__in=ids)
    deleted = decisions.count()
    decisions.delete()
    discarded = ai_screening.discard_unfinished(review, DISCARDED)
    return {"unclassified": unclassified, "decisions_deleted": deleted, "runs_discarded": discarded}
