"""Shared helpers for routers: resolving the review and checking membership."""

from parsifal.apps.core.exceptions import NotFound, PermissionDenied
from parsifal.apps.reviews.models import Review
from parsifal.apps.reviews.services import reviews as review_services


def get_review(request, review_id):
    """The review as seen by a member (author or co-author). Non-members get 404 to avoid leaking existence."""
    try:
        review = Review.objects.select_related("author__profile").get(pk=review_id)
    except Review.DoesNotExist:
        raise NotFound(f"Review {review_id} not found.")
    if not review.is_author_or_coauthor(request.auth):
        raise NotFound(f"Review {review_id} not found.")
    return review


def get_owned_review(request, review_id):
    review = get_review(request, review_id)
    review_services.require_owner(review, request.auth)
    return review


def require_superuser(request):
    if not request.auth.is_superuser:
        raise PermissionDenied("Administrator privileges are required.")
