from datetime import date

from django.db.models import Prefetch, Q

from ninja import Router
from ninja.pagination import LimitOffsetPagination, paginate

from parsifal.api.deps import get_owned_review, get_review
from parsifal.api.v1.schemas.common import UserOut
from parsifal.api.v1.schemas.protocol import SourceOut
from parsifal.api.v1.schemas.reviews import (
    AgentCreatedOut,
    AgentIn,
    AgentOut,
    CodesOut,
    CodesStripIn,
    ProgressOut,
    ReviewCreateIn,
    ReviewEventOut,
    ReviewNameIn,
    ReviewOut,
    ReviewUpdateIn,
    SelectionResetIn,
    SelectionResetOut,
    WrittenCodeOut,
)
from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import Article, Review
from parsifal.apps.reviews.services import agents, codes, history, progress, protocol, reviews, selection

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


@router.get("/reviews/{int:review_id}/codes", response=CodesOut, operation_id="reviews_codes")
def reviews_codes(request, review_id: int):
    """
    The prefixes of the review's codes (research questions RQ1, RQ1.1; criteria IC1, EC1; quality questions QA1;
    extraction fields EX1 — the review numbers them from their order) and the names that start with a code typed by
    hand ("RQ1: …", "EX01 | …"), with what they would become without it.
    """
    review = get_review(request, review_id)
    return {"prefixes": codes.prefixes(review), "written": codes.written(review)}


@router.post("/reviews/{int:review_id}/codes/strip", response=list[WrittenCodeOut], operation_id="reviews_codes_strip")
def reviews_codes_strip(request, review_id: int, payload: CodesStripIn):
    """Remove the codes typed at the start of the names (only ``keys`` when given); returns the names changed."""
    return codes.strip_written(review=get_review(request, review_id), keys=payload.keys, actor=request.auth)


@router.get("/reviews/{int:review_id}/progress", response=ProgressOut, operation_id="reviews_progress")
def reviews_progress(request, review_id: int):
    """
    How far the review has come, as the progress bar shows it: a percentage and its steps. Planning weighs 20%,
    Conducting 70%, Reporting 10%; a protocol step is done with at least one item, a step over the studies counts in
    proportion (screened, assessed, extracted). 100 once every study left has its data extracted and a manuscript
    has a version.
    """
    return progress.progress(get_review(request, review_id))


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


@router.post(
    "/reviews/{int:review_id}/selection/reset", response=SelectionResetOut, operation_id="reviews_selection_reset"
)
def reviews_selection_reset(request, review_id: int, payload: SelectionResetIn):
    """
    Back to the start of study selection (main author only; it cannot be undone): every study that is not a
    duplicate becomes unclassified, without a criterion; the decisions of ``reviewer_ids`` are deleted, at every
    stage; an AI screening run in progress is discarded. Kept: duplicates, the other reviewers' decisions (see
    decisions_summary for who has decisions), the log of the AI runs with their request templates, stars, PDFs,
    quality assessments and extracted data.
    """
    review = get_review(request, review_id)
    return selection.reset(review=review, actor=request.auth, reviewer_ids=payload.reviewer_ids)


@router.put("/reviews/{int:review_id}/name", response=ReviewOut, operation_id="reviews_rename")
def reviews_rename(request, review_id: int, payload: ReviewNameIn):
    return reviews.rename_review(review=get_owned_review(request, review_id), name=payload.name)


@router.get("/reviews/{int:review_id}/history", response=list[ReviewEventOut], operation_id="history_list")
@paginate(LimitOffsetPagination)
def history_list(
    request,
    review_id: int,
    area: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    via: str | None = None,
    article_id: int | None = None,
    since: date | None = None,
    until: date | None = None,
    q: str | None = None,
    amendments: bool | None = None,
):
    """
    The review's History: every change to it, the newest first — who made it (``actor``, a username), when, through
    what (``via``: web, api, cli, mcp or system), in which ``area`` (review, planning, search, studies, selection,
    quality, extraction, analysis), the ``action`` (add, change, remove) and what changed, field by field. Filters:
    those fields; ``article_id``: the changes to one study; ``since``/``until``: dates, both included; ``q``: words
    in what was done, who did it or what changed; ``amendments=true``: only the changes to the protocol made once
    studies were imported (PRISMA 2020 item 24c).
    """
    review = get_review(request, review_id)
    events = history.list_events(
        review,
        area=area,
        action=action,
        actor=actor,
        via=via,
        article_id=article_id,
        since=since,
        until=until,
        query=q,
        amendments=amendments,
    )
    return events.select_related("actor").prefetch_related(Prefetch("articles", Article.objects.only("id")))


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
