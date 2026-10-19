"""
AI agents as co-authors. An agent is an account created for one review (never invited from outside): it works with
the co-author permissions, authenticates with its own API token and everything it records is attributed to it.
Deleting an agent deletes the account itself together with its tokens, screening decisions, quality assessments and
extracted data. Studies it imported and classifications it made stay in the review, without an author.

The Jev agent is the same kind of account, created by the first AI exclusion screening of the review; it has no
token because Parsifal calls Jev itself (see ``ai_screening``).
"""

from dataclasses import dataclass

from django.contrib.auth.models import User
from django.db import transaction
from django.utils.text import slugify

from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.authentication.validators import validate_forbidden_usernames
from parsifal.apps.core.exceptions import NotFound, ValidationError
from parsifal.apps.reviews.models import ReviewAgent
from parsifal.apps.reviews.services._common import check_length, require
from parsifal.apps.reviews.services.reviews import require_owner

NAME_LENGTH = 50
USERNAME_LENGTH = 150
JEV_NAME = "Jev"

# What deleting an agent takes with it; shown to people before they confirm.
DELETION_WARNING = (
    "Deleting an agent permanently deletes its account, its API tokens and everything recorded under it: its "
    "screening decisions, quality assessments and extracted data. Studies it imported and classifications it made "
    "stay in the review, without an author. This cannot be undone."
)


@dataclass
class AgentCreated:
    agent: ReviewAgent
    token: ApiToken
    raw_key: str  # shown once; only its hash is stored


def _username_for(name):
    base = slugify(f"agent-{name}")[: USERNAME_LENGTH - 6] or "agent"
    candidate, index = base, 1
    while True:
        try:
            validate_forbidden_usernames(candidate)
            free = not User.objects.filter(username__iexact=candidate).exists()
        except Exception:
            free = False
        if free:
            return candidate
        index += 1
        candidate = f"{base}-{index}"


def get_agent(review, user_id):
    try:
        return review.agents.select_related("user").get(user_id=user_id)
    except (ReviewAgent.DoesNotExist, ValueError, TypeError):
        raise NotFound(f"Agent {user_id!r} not found in this review.")


def list_agents(review):
    return list(review.agents.select_related("user"))


def stats(agent):
    """How much the agent has recorded: this is what its deletion would remove."""
    user = agent.user
    return {
        "decisions": user.study_decisions.filter(review=agent.review).count(),
        "quality_assessments": user.qualityassessment_set.filter(article__review=agent.review).count(),
        "data_extractions": user.dataextraction_set.filter(article__review=agent.review).count(),
        "active_tokens": user.api_tokens.active().count(),
    }


@transaction.atomic
def create_agent(*, review, actor, name):
    """Create the agent's account, make it a co-author and issue its first token (only the owner can)."""
    require_owner(review, actor)
    name = check_length(require(name, field="name").strip(), NAME_LENGTH, field="name")
    user = User(username=_username_for(name), first_name=name[:150], is_active=True)
    user.set_unusable_password()
    user.save()
    review.co_authors.add(user)
    agent = ReviewAgent.objects.create(review=review, user=user, name=name)
    token, raw_key = ApiToken.create_for(user, name)
    return AgentCreated(agent=agent, token=token, raw_key=raw_key)


@transaction.atomic
def jev_agent(review):
    """
    The review's Jev agent, created on first use. Like any agent it is a co-author with an account of its own, but
    it gets no API token: Parsifal calls Jev and records the decisions under this account.
    """
    agent = review.agents.select_related("user").filter(kind=ReviewAgent.JEV).first()
    if agent is not None:
        return agent
    user = User(username=_username_for(JEV_NAME), first_name=JEV_NAME, is_active=True)
    user.set_unusable_password()
    user.save()
    review.co_authors.add(user)
    return ReviewAgent.objects.create(review=review, user=user, name=JEV_NAME, kind=ReviewAgent.JEV)


@transaction.atomic
def new_token(*, review, actor, agent_id):
    """Revoke every token of the agent and issue a new one."""
    require_owner(review, actor)
    agent = get_agent(review, agent_id)
    if agent.kind == ReviewAgent.JEV:
        raise ValidationError("The Jev agent does not use API tokens.", field="agent_id")
    for token in agent.user.api_tokens.active():
        token.revoke()
    token, raw_key = ApiToken.create_for(agent.user, agent.name)
    return AgentCreated(agent=agent, token=token, raw_key=raw_key)


@transaction.atomic
def delete_agent(*, review, actor, agent_id):
    """Delete the agent's account and everything under it; returns what was deleted (see ``stats``)."""
    require_owner(review, actor)
    agent = get_agent(review, agent_id)
    deleted = stats(agent)
    agent.user.delete()
    return deleted
