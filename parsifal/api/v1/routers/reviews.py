from django.db.models import Q

from ninja import Router
from ninja.pagination import LimitOffsetPagination, paginate

from parsifal.api.deps import get_owned_review, get_review
from parsifal.api.v1.schemas.common import UserOut
from parsifal.api.v1.schemas.protocol import SourceOut
from parsifal.api.v1.schemas.reviews import (
    MemberIn,
    ReviewCreateIn,
    ReviewNameIn,
    ReviewOut,
    ReviewUpdateIn,
    TransferIn,
)
from parsifal.apps.core.exceptions import PermissionDenied, ValidationError
from parsifal.apps.reviews.models import Review
from parsifal.apps.reviews.services import protocol, reviews

router = Router(tags=["reviews"])


@router.get("/sources/defaults", response=list[SourceOut], operation_id="sources_defaults")
def sources_defaults(request):
    return protocol.list_default_sources()


@router.get("/reviews", response=list[ReviewOut], operation_id="reviews_list")
@paginate(LimitOffsetPagination)
def reviews_list(request, author: str | None = None, name: str | None = None, q: str | None = None):
    """Reviews the current user takes part in (every review for administrators)."""
    user = request.auth
    queryset = Review.objects.select_related("author").prefetch_related("co_authors").order_by("-last_update")
    if not user.is_superuser:
        queryset = queryset.filter(Q(author=user) | Q(co_authors=user)).distinct()
    if author:
        queryset = queryset.filter(author__username__iexact=author)
    if name:
        queryset = queryset.filter(name=name)
    if q:
        queryset = queryset.filter(Q(title__icontains=q) | Q(description__icontains=q))
    return queryset


@router.post("/reviews", response={201: ReviewOut}, operation_id="reviews_create")
def reviews_create(request, payload: ReviewCreateIn):
    review = reviews.create_review(actor=request.auth, title=payload.title, description=payload.description)
    if payload.review_type != review.review_type:
        review = reviews.update_review(review=review, review_type=payload.review_type)
    return 201, review


@router.get("/reviews/{int:review_id}", response=ReviewOut, operation_id="reviews_get")
def reviews_get(request, review_id: int):
    return get_review(request, review_id)


@router.get("/reviews/{int:review_id}/overview", response=dict, operation_id="reviews_overview")
def reviews_overview(request, review_id: int):
    """Counts per protocol section and per article status — what an agent needs to decide the next step."""
    return reviews.review_overview(get_review(request, review_id))


@router.patch("/reviews/{int:review_id}", response=ReviewOut, operation_id="reviews_update")
def reviews_update(request, review_id: int, payload: ReviewUpdateIn):
    review = get_review(request, review_id)
    fields = payload.dict(exclude_unset=True)
    if not fields:
        raise ValidationError("No fields to update.")
    return reviews.update_review(review=review, **fields)


@router.delete("/reviews/{int:review_id}", response={204: None}, operation_id="reviews_delete")
def reviews_delete(request, review_id: int):
    reviews.delete_review(review=get_owned_review(request, review_id))
    return 204, None


@router.put("/reviews/{int:review_id}/name", response=ReviewOut, operation_id="reviews_rename")
def reviews_rename(request, review_id: int, payload: ReviewNameIn):
    return reviews.rename_review(review=get_owned_review(request, review_id), name=payload.name)


@router.post("/reviews/{int:review_id}/transfer", response=ReviewOut, operation_id="reviews_transfer")
def reviews_transfer(request, review_id: int, payload: TransferIn):
    review = get_owned_review(request, review_id)
    to_user = reviews.find_user(username=payload.username)
    return reviews.transfer_review(review=review, actor=request.auth, to_user=to_user)


@router.get("/reviews/{int:review_id}/members", response=list[UserOut], operation_id="members_list")
def members_list(request, review_id: int):
    review = get_review(request, review_id)
    return [review.author, *review.co_authors.order_by("username")]


@router.post("/reviews/{int:review_id}/members", response={201: UserOut}, operation_id="members_add")
def members_add(request, review_id: int, payload: MemberIn):
    """Add an existing account as co-author directly (main author only); the web UI uses e-mail invites."""
    review = get_owned_review(request, review_id)
    if not payload.username and not payload.email:
        raise ValidationError("Provide username or email.")
    user = reviews.find_user(username=payload.username, email=payload.email)
    reviews.add_co_author(review=review, user=user)
    return 201, user


@router.delete("/reviews/{int:review_id}/members/{int:user_id}", response={204: None}, operation_id="members_remove")
def members_remove(request, review_id: int, user_id: int):
    """Main author removes a co-author, or a co-author removes themselves (leave)."""
    review = get_review(request, review_id)
    if user_id != request.auth.pk and review.author_id != request.auth.pk:
        raise PermissionDenied("Only the main author can remove other co-authors.")
    user = reviews.find_user_by_id(user_id)
    reviews.remove_co_author(review=review, user=user)
    return 204, None
