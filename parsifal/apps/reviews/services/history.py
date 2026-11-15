"""
The History of a review: each change to it — who made it, when, through what (the web, the API, the CLI, the MCP
server) and what changed, field by field — for the people who follow the review. The services record the changes,
and so do the web views that do not go through them; nobody edits or deletes an event.

Who acts and through what come from the request being served (``HistoryMiddleware`` sets it), or from ``acting``
outside one. A change to the protocol (Planning) once studies were imported is marked as an amendment, which PRISMA
2020 asks to report (item 24c).
"""

import contextlib
import contextvars
import datetime
from dataclasses import dataclass

from django.db.models import Count, Q
from django.utils import timezone

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import Article, ReviewEvent

ADDED, CHANGED, REMOVED = ReviewEvent.ADDED, ReviewEvent.CHANGED, ReviewEvent.REMOVED
MAX_ITEMS = 1000  # names kept in one event; the rest are counted
STUDIES_SHOWN = 50  # studies of an event listed on the History page

_current = contextvars.ContextVar("parsifal_history", default=None)


@dataclass(frozen=True)
class _Context:
    request: object = None
    actor: object = None
    via: str = ReviewEvent.SYSTEM


@contextlib.contextmanager
def acting(actor=None, via=ReviewEvent.SYSTEM, *, request=None):
    """The changes made inside are ``actor``'s through ``via`` (or those of ``request``'s user, through it)."""
    token = _current.set(_Context(request=request, actor=actor, via=via))
    try:
        yield
    finally:
        _current.reset(token)


class HistoryMiddleware:
    """Every change made while serving a request is its user's, through the web or the API."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with acting(request=request):
            return self.get_response(request)


def _via(request):
    """The browser, or a client with a token: the CLI, the MCP server or another program."""
    if not request.headers.get("Authorization", "").startswith("Bearer "):
        return ReviewEvent.WEB
    agent = request.headers.get("User-Agent", "")
    if agent.startswith("parsifal-mcp/"):
        return ReviewEvent.MCP
    if agent.startswith("parsifal-cli/"):
        return ReviewEvent.CLI
    return ReviewEvent.API


def current():
    """(who acts, through what) now; the user is read when asked, since the API authenticates late."""
    context = _current.get()
    if context is None:
        return None, ReviewEvent.SYSTEM
    if context.request is not None:
        user = getattr(context.request, "user", None)
        return (user if user is not None and user.is_authenticated else None), _via(context.request)
    return context.actor, context.via


def _name(user):
    if user is None:
        return ""
    return user.get_full_name() or user.username


def record(
    review,
    area,
    action,
    summary,
    *,
    subject="",
    subject_id=None,
    changes=(),
    items=(),
    articles=(),
    run=None,
    actor=None,
):
    """
    Record a change to ``review``: ``summary`` says what was done, without who ("Added the exclusion criterion
    “X”"); ``changes`` lists each field changed ({"field", "before", "after"}); ``items`` names what it applied to
    when there is no study to point to; ``articles`` are the studies (or their ids) it applied to. ``actor``
    defaults to whoever acts now.
    """
    who, via = current()
    actor = actor or who
    items = [str(item) for item in items]
    if len(items) > MAX_ITEMS:
        items = items[:MAX_ITEMS] + [f"… and {len(items) - MAX_ITEMS} more"]
    event = ReviewEvent.objects.create(
        review=review,
        actor_id=getattr(actor, "pk", None),
        actor_name=_name(actor)[:150],
        via=via,
        area=area,
        action=action,
        summary=summary[:500],
        subject=subject,
        subject_id=subject_id,
        changes=list(changes),
        items=items,
        run=run,
        amendment=area == ReviewEvent.PLANNING and review.article_set.exists(),
    )
    ids = {getattr(article, "pk", article) for article in articles}
    if ids:
        through = ReviewEvent.articles.through
        through.objects.bulk_create(
            [through(reviewevent_id=event.pk, article_id=pk) for pk in sorted(ids)], batch_size=500
        )
    return event


# What changed --------------------------------------------------------------------------------------------------------


def label(model, name):
    """The field's name for people: its verbose name, capitalised."""
    text = str(model._meta.get_field(name).verbose_name)
    return text[:1].upper() + text[1:]


def show(value):
    """A value as the History shows it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return ", ".join(show(item) for item in value)
    return str(value)


def _value(obj, name):
    field = obj._meta.get_field(name)
    if field.choices:
        value = getattr(obj, field.attname)
        return show(dict(field.flatchoices).get(value, value))
    return show(getattr(obj, name))


def change(field, before, after, key=""):
    return {"key": key, "field": field, "before": show(before), "after": show(after)}


class Tracker:
    """The fields of ``obj`` as they are now, to tell later which ones changed (``labels``: names for people)."""

    def __init__(self, obj, fields, labels=None):
        self.obj, self.fields, self.labels = obj, tuple(fields), labels or {}
        self.before = {name: _value(obj, name) for name in self.fields}

    def changes(self):
        found = []
        for name in self.fields:
            after = _value(self.obj, name)
            if after != self.before[name]:
                field = self.labels.get(name) or label(type(self.obj), name)
                found.append({"key": name, "field": field, "before": self.before[name], "after": after})
        return found


def track(obj, *fields):
    return Tracker(obj, fields)


def quote(text, limit=80):
    """“text”, shortened, for a summary."""
    text = " ".join(str(text or "").split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f"“{text}”"


def studies(count):
    return f"{count} stud{'y' if count == 1 else 'ies'}"


def plural(count, word, words=None):
    return f"{count} {word if count == 1 else (words or word + 's')}"


def filled(obj, fields, labels=None, removed=False):
    """The fields that have a value, as changes from nothing (added) or to nothing (removed)."""
    found = []
    for name in fields:
        value = _value(obj, name)
        if value:
            before, after = (value, "") if removed else ("", value)
            field = (labels or {}).get(name) or label(type(obj), name)
            found.append({"key": name, "field": field, "before": before, "after": after})
    return found


@dataclass(frozen=True)
class Kind:
    """
    Something of a review whose changes the History records alike wherever they are made (a service, a web view):
    its name for people ("research question"), its area and its fields, the first one naming it.
    """

    name: str
    area: str
    fields: tuple
    plural: str = ""
    labels: tuple = ()  # (field, its name for people) where the model's verbose name does not do

    @property
    def subject(self):
        return self.name.replace(" ", "_")

    def named(self, obj):
        return _value(obj, self.fields[0])

    def track(self, obj):
        return Tracker(obj, self.fields, dict(self.labels))

    def _record(self, review, action, verb, obj, changes, name, suffix, **extra):
        summary = f"{verb} the {self.name} {quote(name if name is not None else self.named(obj))}{suffix}"
        return record(
            review, self.area, action, summary, subject=self.subject, subject_id=obj.pk, changes=changes, **extra
        )

    def added(self, review, obj, *, name=None, suffix="", changes=(), **extra):
        changes = [*filled(obj, self.fields, dict(self.labels)), *changes]
        return self._record(review, ADDED, "Added", obj, changes, name, suffix, **extra)

    def changed(self, review, tracker, *, name=None, suffix="", changes=(), **extra):
        """Records what changed since ``tracker`` (see ``track``), when something did; returns the event or None."""
        changes = [*tracker.changes(), *changes]
        if not changes:
            return None
        return self._record(review, CHANGED, "Changed", tracker.obj, changes, name, suffix, **extra)

    def removed(self, review, obj, *, name=None, suffix="", changes=(), **extra):
        """Before deleting ``obj``."""
        changes = [*filled(obj, self.fields, dict(self.labels), True), *changes]
        return self._record(review, REMOVED, "Removed", obj, changes, name, suffix, **extra)

    def order(self, queryset):
        """The objects' ids in their order, for ``reordered``."""
        return list(queryset.order_by("order", "pk").values_list("pk", flat=True))

    def reordered(self, review, queryset, before):
        """Records the new order of ``queryset`` when it is not ``before`` (see ``order``)."""
        objects = list(queryset.order_by("order", "pk"))
        if [obj.pk for obj in objects] == before:
            return None
        summary = f"Reordered the {self.plural or self.name + 's'}"
        items = [self.named(obj) for obj in objects]
        return record(review, self.area, CHANGED, summary, subject=self.subject, items=items)


# Reading -------------------------------------------------------------------------------------------------------------


def _date(value, field):
    if value in (None, ""):
        return None
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        raise ValidationError(f"{field} must be a date (YYYY-MM-DD).", field=field)


def list_events(
    review,
    *,
    area=None,
    action=None,
    actor=None,
    via=None,
    article_id=None,
    since=None,
    until=None,
    query=None,
    amendments=None,
):
    """
    The review's events, the newest first. ``actor``: a username; ``since``/``until``: dates (YYYY-MM-DD, both
    included); ``query``: words in what was done, who did it or what changed; ``amendments``: only the changes to
    the protocol made once studies were imported (False: the others).
    """
    events = review.events.select_related("run")
    for value, field, choices in (
        (area, "area", ReviewEvent.AREAS),
        (action, "action", ReviewEvent.ACTIONS),
        (via, "via", ReviewEvent.VIA),
    ):
        if value:
            if value not in dict(choices):
                raise ValidationError(f"{field} must be one of {[key for key, _ in choices]}.", field=field)
            events = events.filter(**{field: value})
    if actor:
        events = events.filter(actor__username__iexact=actor)
    if article_id:
        events = events.filter(articles=article_id)
    since, until = _date(since, "since"), _date(until, "until")
    if since:
        events = events.filter(created_at__gte=_start_of(since))
    if until:
        events = events.filter(created_at__lt=_start_of(until + datetime.timedelta(days=1)))
    for word in (query or "").split():
        events = events.filter(Q(summary__icontains=word) | Q(actor_name__icontains=word) | Q(changes__icontains=word))
    if amendments is not None:
        events = events.filter(amendment=bool(amendments))
    return events.annotate(study_count=Count("articles")).order_by("-created_at", "-pk")


def _start_of(day):
    """The first moment of ``day`` where the review is followed (the server's time zone)."""
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))


def actors(review):
    """Who appears in the review's history, as (username, name), for the filter; former accounts have no username."""
    rows = review.events.exclude(actor=None).values_list("actor__username", "actor_name").order_by("actor_name")
    names = {}
    for username, name in rows:
        names.setdefault(username, name or username)
    return sorted(names.items(), key=lambda row: row[1].lower())


def event_studies(event, limit=STUDIES_SHOWN):
    """The first studies an event applied to (the History lists them), by title."""
    return list(Article.objects.filter(events=event).order_by("title").only("id", "title", "status")[:limit])
