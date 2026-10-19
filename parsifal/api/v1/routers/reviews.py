from django.db.models import Q

from ninja import Router
from ninja.pagination import LimitOffsetPagination, paginate

from parsifal.api.deps import get_owned_review, get_review
from parsifal.api.v1.schemas.common import UserOut
from parsifal.api.v1.schemas.protocol import SourceOut
from parsifal.api.v1.schemas.reviews import (
    AgentCreatedOut,
    AgentIn,
    AgentOut,
    ReviewCreateIn,
    ReviewNameIn,
    ReviewOut,
    ReviewUpdateIn,
)
from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import Review
from parsifal.apps.reviews.services import agents, protocol, reviews

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


@router.get("/reviews/{int:review_id}/members", response=list[UserOut], operation_id="members_list")
def members_list(request, review_id: int):
    review = get_review(request, review_id)
    return [review.author, *review.co_authors.order_by("username")]


def _agent_out(agent, created=None):
    data = dict(
        id=agent.user_id,
        name=agent.name,
        username=agent.user.username,
        created_at=agent.created_at,
        **agents.stats(agent),
    )
    if created is not None:
        return AgentCreatedOut(token=created.raw_key, **data)
    return AgentOut(**data)


@router.get("/reviews/{int:review_id}/agents", response=list[AgentOut], operation_id="agents_list")
def agents_list(request, review_id: int):
    """AI agents of the review, with how much each has recorded (what deleting it would remove)."""
    return [_agent_out(agent) for agent in agents.list_agents(get_review(request, review_id))]


@router.post("/reviews/{int:review_id}/agents", response={201: AgentCreatedOut}, operation_id="agents_create")
def agents_create(request, review_id: int, payload: AgentIn):
    """
    Create an AI agent as co-author of the review (main author only): an account of its own with co-author
    permissions and an API token. The token is in the response and is never shown again.
    """
    review = get_owned_review(request, review_id)
    created = agents.create_agent(review=review, actor=request.auth, name=payload.name)
    return 201, _agent_out(created.agent, created)


@router.post(
    "/reviews/{int:review_id}/agents/{int:agent_id}/token",
    response=AgentCreatedOut,
    operation_id="agents_new_token",
)
def agents_new_token(request, review_id: int, agent_id: int):
    """Revoke every token of the agent and issue a new one (main author only); the new token is shown once."""
    review = get_owned_review(request, review_id)
    created = agents.new_token(review=review, actor=request.auth, agent_id=agent_id)
    return _agent_out(created.agent, created)


@router.delete("/reviews/{int:review_id}/agents/{int:agent_id}", response={204: None}, operation_id="agents_delete")
def agents_delete(request, review_id: int, agent_id: int):
    """
    Delete the agent (main author only). PERMANENT: deletes its account, its API tokens and everything recorded
    under it, namely its screening decisions, quality assessments and extracted data. Studies it imported and
    classifications it made stay in the review, without an author.
    """
    review = get_owned_review(request, review_id)
    agents.delete_agent(review=review, actor=request.auth, agent_id=agent_id)
    return 204, None
