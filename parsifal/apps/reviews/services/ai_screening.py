"""
AI screening of study selection. Jev reads each study (by default its title and abstract; never authors, venue or
affiliations) and answers about the review's criteria, in one of three actions, run in any order:

- **Exclude with AI**: which exclusion criterion, if any, the study meets. One is enough to reject it.
- **Include with AI**: whether the study meets each inclusion criterion. The protocol says whether all of them must
  be met or at least one (``Review.inclusion_rule``). It never rejects: what it does not accept is left to the
  reviewers.
- **Screen with AI**: both, in the same request. Exclusion wins: a study that meets an exclusion criterion is
  rejected even when it also meets the inclusion criteria; otherwise it is accepted when it meets them, or left
  undecided.

(Retain with AI, one retention question per study, was removed; its runs remain in the history.)

Every run is made in the name of a **reviewer** chosen by whoever starts it (the main author may pick any member of
the review, anyone else only themselves), so one person can screen as several reviewers and compare them. A run
sends the studies with the chosen statuses and the criteria chosen (all of them, or some: those Jev cannot judge
from a title and abstract, such as the year or the full text's availability, can be left out), and rewrites this
reviewer's decisions: nothing is skipped because it was evaluated before, so two reviewers can screen the same
studies and be compared (Reviewer agreement).

A new run of an action starts from every setting of the review's last run of that action (reviewer, model, context,
guidance, request, thresholds, criteria, studies), or from Parsifal's defaults when asked (``starting_settings``).

A run records the reviewer's decision on every study it screens, but changes a study's **status** only when the
study is unclassified, or was classified by this same reviewer with a status the action decides (exclusion: rejected;
inclusion: accepted; screen: either). Duplicates and studies classified by someone else keep their status, and so
do accepted studies in an exclusion run and rejected studies in an inclusion run.

What is sent for each study is a template the reviewer can edit around the data (``screening_requests``): the review
context, the criteria and the study are filled in by Parsifal; the rest (task, rules, how the answers are worded,
where each part goes) is the template's, kept in the run's parameters.

Every question is asked once and its answer is read as it comes.

Exclusion: the exclusion criteria plus a "none" option go in one choice question. Because the probabilities of a
choice sum to 1, the probability that *some* criterion applies is ``1 - p(none)``, even when two criteria split it.
``1 - p(none) >= threshold`` rejects the study with the most probable criterion; otherwise the reviewer's decision is
"unclassified" (no criterion applies) and a study this reviewer had rejected goes back to unclassified.

Inclusion: one yes/no question (Jev's "noul") per inclusion criterion; the answer is the probability that the study
meets the criterion, p(meets), compared with that criterion's own threshold. With the rule "all", every criterion
must reach its threshold (an average would let a criterion that is clearly met make up for one that is not); with
"any", one is enough. Met: the study is accepted. Otherwise the reviewer's decision is "unclassified" (undecided)
and a study this reviewer had accepted goes back to unclassified.

A run is driven in small steps (``process_step``) so that the page can show its progress, and every answer is kept
in ``ScreeningResult`` for audit. A run cannot be stopped; when it is interrupted (page closed, connection lost, Jev
refusing the key or unavailable) it keeps its remaining studies and is continued by calling ``process_step`` again,
with the parameters it started with. Starting a new run discards an unfinished one.
"""

from concurrent.futures import ThreadPoolExecutor

from django.db import transaction
from django.db.models import Case, Count, F, FloatField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Least
from django.utils import timezone

from parsifal.apps.accounts import services as integrations
from parsifal.apps.core import jev
from parsifal.apps.core.exceptions import NotFound, PermissionDenied, ValidationError
from parsifal.apps.reviews.models import Article, Review, ReviewAgent, ScreeningResult, ScreeningRun, StudyDecision
from parsifal.apps.reviews.services import decisions, screening_requests
from parsifal.apps.reviews.services._common import check_length, get_child

DEFAULT_THRESHOLD = 0.9
MIN_THRESHOLD = 0.5
MAX_THRESHOLD = 0.99
STEP_SIZE = 64  # studies per step; one request each
ACTIVE_FOR = 30  # seconds: a running run with a step this recent is being driven somewhere
# A step is one HTTP request: 64 studies take a few seconds, well within the server's timeout even when Jev is slow.
MAX_STEP_SIZE = 64
# Concurrent requests to Jev within a step; the client spaces them under Jev's rate limit (JEV_REQUESTS_PER_MINUTE).
# About 32 keep that limit busy (16 reached about 11 studies a second against the limit's 18).
WORKERS = 32
NONE = screening_requests.NONE
INCLUSION_QUESTION = screening_requests.NOUL  # Jev's yes/no question: the answer is the probability of yes

# Review context sent with every study; editable before a run, defaults taken from the review.
CONTEXT_FIELDS = (
    ("title", "Review title", 255),
    ("objective", "Objective", 1000),
    ("research_questions", "Research questions", 5000),
    ("population", "Population", 200),
    ("intervention", "Intervention", 200),
    ("comparison", "Comparison", 200),
    ("outcome", "Outcome", 200),
    ("context", "Context", 200),
)
GUIDANCE_LENGTH = 2000

EXCLUSION, INCLUSION, SCREEN = ScreeningRun.EXCLUSION, ScreeningRun.INCLUSION, ScreeningRun.SCREEN
RETENTION = ScreeningRun.RETENTION  # removed: only its runs in the history
ACTIONS = (EXCLUSION, INCLUSION, SCREEN)  # what a run can be started as
LABELS = {
    EXCLUSION: "Exclude with AI",
    INCLUSION: "Include with AI",
    SCREEN: "Screen with AI",
    RETENTION: "Retain with AI",
}
INCLUDE_ALL, INCLUDE_ANY = Review.INCLUDE_ALL, Review.INCLUDE_ANY

# Statuses of the studies a run may send, in the order the window lists them.
STATUSES = (
    (Article.ACCEPTED, "Accepted"),
    (Article.REJECTED, "Rejected"),
    (Article.UNCLASSIFIED, "Unclassified"),
    (Article.DUPLICATED, "Duplicated"),
)
DEFAULT_STATUSES = {
    EXCLUSION: (Article.REJECTED, Article.UNCLASSIFIED),
    INCLUSION: (Article.UNCLASSIFIED, Article.ACCEPTED),
    SCREEN: (Article.ACCEPTED, Article.REJECTED, Article.UNCLASSIFIED),
}
# The statuses a run may change (when unclassified, or set by its reviewer): what it can decide.
CHANGEABLE = {
    EXCLUSION: {Article.UNCLASSIFIED, Article.REJECTED},
    INCLUSION: {Article.UNCLASSIFIED, Article.ACCEPTED},
    SCREEN: {Article.UNCLASSIFIED, Article.ACCEPTED, Article.REJECTED},
}


# Setup ---------------------------------------------------------------------------------------------------------------


def reviewer_choices(review, actor):
    """
    Who ``actor`` may screen as: the main author may choose any member of the review (themselves, people, AI
    agents); anyone else only themselves, so an agent can never record decisions in someone else's name.
    """
    members = [review.author, *review.co_authors.order_by("first_name", "username")]
    if actor.pk == review.author_id:
        return members
    return [member for member in members if member.pk == actor.pk]


def agent_ids(review):
    return set(ReviewAgent.objects.filter(review=review).values_list("user_id", flat=True))


def get_reviewer(review, actor, reviewer_id):
    if reviewer_id in (None, ""):
        raise ValidationError("Choose the reviewer the decisions are recorded as.", field="reviewer_id")
    members = {str(member.pk): member for member in (review.author, *review.co_authors.all())}
    reviewer = members.get(str(reviewer_id))
    if reviewer is None:
        raise NotFound(f"Reviewer {reviewer_id!r} is not a member of this review.", field="reviewer_id")
    if actor.pk != review.author_id and reviewer.pk != actor.pk:
        raise PermissionDenied("Only the main author can screen in the name of another reviewer.", field="reviewer_id")
    return reviewer


def last_reviewer_id(review):
    """The reviewer of the review's latest run, to preselect it."""
    return review.screening_runs.values_list("reviewer_id", flat=True).first()


def default_context(review):
    """The review's own values for the editable context fields."""
    return {
        "title": review.title,
        "objective": review.objective,
        "research_questions": "\n".join(question.question for question in review.research_questions.all()),
        "population": review.population,
        "intervention": review.intervention,
        "comparison": review.comparison,
        "outcome": review.outcome,
        "context": review.context,
    }


def clean_phase(phase):
    """The action of a new run: exclusion (the default), inclusion or screen."""
    phase = str(phase or EXCLUSION).strip().lower()
    if phase == RETENTION:
        raise ValidationError(
            "Retain with AI was removed: use Screen with AI (exclusion and inclusion in one request).", field="phase"
        )
    if phase not in ACTIONS:
        raise ValidationError(f"phase must be {EXCLUSION}, {INCLUSION} or {SCREEN}.", field="phase")
    return phase


def exclusion_options(review):
    """The review's exclusion criteria as the options of the question: E1, E2… in the order the review lists them."""
    return [
        {"key": f"E{index}", "id": criteria.pk, "description": criteria.description}
        for index, criteria in enumerate(review.get_exclusion_criterias(), start=1)
    ]


def inclusion_options(review):
    """The review's inclusion criteria, one question each: I1, I2… in the order the review lists them."""
    return [
        {"key": f"I{index}", "id": criteria.pk, "description": criteria.description}
        for index, criteria in enumerate(review.get_inclusion_criterias(), start=1)
    ]


def criteria_options(review, phase):
    """The criteria a run of ``phase`` may send: Screen with AI, the exclusion ones and then the inclusion ones."""
    if phase == SCREEN:
        return exclusion_options(review) + inclusion_options(review)
    return inclusion_options(review) if phase == INCLUSION else exclusion_options(review)


def criteria_name(phase):
    """What the criteria of ``phase`` are called, for messages."""
    return "exclusion and inclusion criteria" if phase == SCREEN else f"{phase} criteria"


def _ids(values, field="criteria_ids"):
    if isinstance(values, (str, int)):
        values = [values]
    try:
        return {int(value) for value in values if str(value).strip()}
    except (TypeError, ValueError):
        raise ValidationError("Criteria are given by their ids (numbers).", field=field)


def clean_criteria(review, phase, criteria_ids=None):
    """
    The criteria a run of ``phase`` sends, as options (``criteria_options``), and the ids of those left out:
    ``criteria_ids`` picks them (None: all of them). Exclusion needs at least one exclusion criterion, inclusion one
    inclusion criterion, Screen with AI one of each.
    """
    options = criteria_options(review, phase)
    kinds = {EXCLUSION: ("E",), INCLUSION: ("I",), SCREEN: ("E", "I")}[phase]
    names = {"E": "exclusion", "I": "inclusion"}
    for kind in kinds:
        if not any(option["key"].startswith(kind) for option in options):
            needs = f" {LABELS[phase]} asks about both." if phase == SCREEN else ""
            raise ValidationError(
                f"The review has no {names[kind]} criteria.{needs} Add them in Planning first.", field="criteria"
            )
    if criteria_ids is None:
        return options, []
    chosen = _ids(criteria_ids)
    unknown = sorted(chosen - {option["id"] for option in options})
    if unknown:
        raise ValidationError(
            f"Criterion {', '.join(map(str, unknown))} is not one of the review's {criteria_name(phase)}.",
            field="criteria_ids",
        )
    selected = [option for option in options if option["id"] in chosen]
    for kind in kinds:
        if not any(option["key"].startswith(kind) for option in selected):
            raise ValidationError(f"Choose at least one {names[kind]} criterion to send.", field="criteria_ids")
    return selected, [option["id"] for option in options if option["id"] not in chosen]


def last_run(review, phase):
    """The review's latest run of ``phase``, or None."""
    return review.screening_runs.filter(phase=phase).first()


def run_settings(review, run):
    """
    The settings of a new run like ``run``, as ``start_run`` takes them: the same action, reviewer, model, context,
    guidance, request template, thresholds, source, statuses and criteria. The criteria are the review's current
    ones: those the run left out stay out, a criterion added since is sent; an inclusion criterion keeps the
    threshold the run gave it, a new one takes the default.
    """
    phase = clean_phase(run.phase)
    parameters = run.parameters
    source_id = parameters.get("source_id")
    if source_id and not review.sources.filter(pk=source_id).exists():
        source_id = None
    skipped = set(parameters.get("skipped_criteria", []))
    settings = {
        "phase": phase,
        "reviewer_id": run.reviewer_id,
        "model": run.model,
        "context": parameters.get("context") or None,
        "guidance": parameters.get("guidance") or "",
        # Runs from before request templates were editable used the default.
        "template": parameters.get("template") or screening_requests.default(phase),
        "source_id": source_id,
        "statuses": parameters.get("statuses"),
        "criteria_ids": [option["id"] for option in criteria_options(review, phase) if option["id"] not in skipped],
        "threshold": None,
        "thresholds": None,
    }
    if phase in (INCLUSION, SCREEN):
        settings["thresholds"] = thresholds_like(parameters, inclusion_options(review))
    if phase in (EXCLUSION, SCREEN):
        settings["threshold"] = parameters.get("threshold")
    return settings


def starting_settings(review, phase, *, defaults=False):
    """
    The settings a new run of ``phase`` starts from (``run_settings``): those of the review's last run of that
    action, or Parsifal's defaults when there is none or ``defaults`` — the review's context, the default request,
    every criterion, threshold 0.9, the action's default statuses, all sources and the actor's default model (None).
    ``run`` is the run they come from, or None.
    """
    phase = clean_phase(phase)
    run = None if defaults else last_run(review, phase)
    if run is not None:
        return {**run_settings(review, run), "run": run}
    inclusion = inclusion_options(review)
    return {
        "phase": phase,
        "reviewer_id": last_reviewer_id(review),
        "model": None,
        "context": default_context(review),
        "guidance": "",
        "template": screening_requests.default(phase),
        "source_id": None,
        "statuses": clean_statuses(None, phase),
        "criteria_ids": [option["id"] for option in criteria_options(review, phase)],
        "threshold": DEFAULT_THRESHOLD if phase in (EXCLUSION, SCREEN) else None,
        "thresholds": (
            dict.fromkeys((option["key"] for option in inclusion), DEFAULT_THRESHOLD)
            if phase in (INCLUSION, SCREEN)
            else None
        ),
        "run": None,
    }


def clean_statuses(statuses, phase=EXCLUSION):
    """
    The statuses of the studies to send: codes U, R, A, D; None means the action's default (exclusion: rejected and
    unclassified; inclusion: unclassified and accepted; screen: all but duplicates).
    """
    if statuses is None:
        return [code for code, _label in STATUSES if code in DEFAULT_STATUSES[phase]]
    if isinstance(statuses, str):
        statuses = [statuses]
    codes = dict(STATUSES)
    chosen = {str(status).strip().upper() for status in statuses if str(status).strip()}
    unknown = sorted(chosen - set(codes))
    if unknown:
        raise ValidationError(f"Unknown status {', '.join(unknown)}: use U, R, A or D.", field="statuses")
    if not chosen:
        raise ValidationError("Choose the statuses of the studies to send.", field="statuses")
    return [code for code, _label in STATUSES if code in chosen]


def eligible_articles(review, *, statuses=DEFAULT_STATUSES[EXCLUSION], source_id=None):
    """What a run sends: the studies with ``statuses``, from one source or all of them."""
    articles = review.article_set.filter(status__in=statuses)
    if source_id:
        articles = articles.filter(source_id=source_id)
    return articles.order_by("pk")


def scope_counts(review):
    """
    Studies per scope and status, to count what a run would send: {"": {"U": n, …}, "<source id>": {"U": n, …}},
    every status present (0 when there is none).
    """
    empty = {code: 0 for code, _label in STATUSES}
    counts = {"": dict(empty)}
    for row in review.article_set.order_by().values("source_id", "status").annotate(n=Count("pk")):
        if row["status"] not in empty:
            continue
        counts[""][row["status"]] += row["n"]
        counts.setdefault(str(row["source_id"]), dict(empty))[row["status"]] = row["n"]
    return counts


def _clean_context(context, guidance):
    cleaned = {}
    for name, _label, limit in CONTEXT_FIELDS:
        cleaned[name] = check_length(str(context.get(name) or "").strip(), limit, field=name)
    return cleaned, check_length(str(guidance or "").strip(), GUIDANCE_LENGTH, field="guidance")


def threshold_range():
    """(default, lowest, highest) threshold."""
    return DEFAULT_THRESHOLD, MIN_THRESHOLD, MAX_THRESHOLD


def _threshold(value, *, label="The threshold", field="threshold"):
    try:
        value = round(float(value), 4)
    except (TypeError, ValueError):
        raise ValidationError(f"{label} must be a number.", field=field)
    if not MIN_THRESHOLD <= value <= MAX_THRESHOLD:
        raise ValidationError(f"{label} must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}.", field=field)
    return value


def clean_threshold(threshold):
    """
    The exclusion threshold (exclusion and screen runs), 0.5–0.99 (None: 0.9): reject when some exclusion criterion
    applies with at least this probability. In an inclusion run it is the threshold of the criteria ``thresholds``
    leaves out.
    """
    return DEFAULT_THRESHOLD if threshold is None else _threshold(threshold)


def thresholds_like(parameters, options):
    """
    The threshold of each inclusion criterion of ``options``, {I1: 0.9, …}, as the ``parameters`` of an inclusion run
    gave it (criteria matched by id, so a criterion keeps its threshold when the keys change), else that run's single
    threshold (older runs), else 0.9.
    """
    fallback, by_id = DEFAULT_THRESHOLD, {}
    if "thresholds" in parameters:
        ids = {option["key"]: option["id"] for option in parameters.get("criteria", [])}
        by_id = {ids[key]: value for key, value in parameters["thresholds"].items() if key in ids}
    elif parameters.get("threshold") is not None:
        fallback = parameters["threshold"]
    return {option["key"]: by_id.get(option["id"], fallback) for option in options}


def _given_thresholds(thresholds):
    """{key: value} from an object, or from texts written KEY=value (as the CLI sends them)."""
    if thresholds in (None, ""):
        return {}
    if isinstance(thresholds, dict):
        return {str(key).strip().upper(): value for key, value in thresholds.items()}
    if isinstance(thresholds, str):
        thresholds = [thresholds]
    given = {}
    for text in thresholds:
        key, separator, value = str(text).partition("=")
        if not separator or not key.strip():
            raise ValidationError("Write each threshold as KEY=value, e.g. I1=0.9.", field="thresholds")
        given[key.strip().upper()] = value.strip()
    return given


def clean_thresholds(options, thresholds=None, threshold=None, base=None):
    """
    The threshold of each inclusion criterion of ``options`` (those sent), {I1: 0.9, …}, each 0.5–0.99:
    ``thresholds`` ({I1: 0.9, …} or ["I1=0.9", …]) for the criteria it gives; for the others, ``threshold`` when
    given, else ``base`` (the settings the run starts from, see ``starting_settings``), else 0.9.
    """
    given = _given_thresholds(thresholds)
    keys = [option["key"] for option in options]
    unknown = sorted(set(given) - set(keys))
    if unknown:
        raise ValidationError(
            f"Unknown inclusion criterion {', '.join(unknown)}: the run sends {', '.join(keys)}.", field="thresholds"
        )
    if threshold is None:
        rest = {key: (base or {}).get(key, DEFAULT_THRESHOLD) for key in keys}
    else:
        rest = dict.fromkeys(keys, clean_threshold(threshold))
    return {
        key: _threshold(given[key], label=f"The threshold of {key}", field="thresholds") if key in given else rest[key]
        for key in keys
    }


# Request ------------------------------------------------------------------------------------------------------------


def state(article):
    """
    What Parsifal may send about a study: its title, keywords and abstract that are not empty (the study
    placeholders of the request template), or None when there is nothing to read.
    """
    values = {
        "title": article.title,
        "keywords": article.author_keywords or article.keywords,
        "abstract": article.abstract,
    }
    values = {name: value.strip() for name, value in values.items() if value and value.strip()}
    if "title" not in values and "abstract" not in values:
        return None
    return values


def build_request(phase, template, options, context, guidance, study):
    """The ``state`` and ``questions`` sent to Jev about one study (``study``: see ``state``)."""
    values = screening_requests.values(context, guidance, study)
    return screening_requests.build(phase, template, options, values)


def _probability(value):
    try:
        return round(min(max(float(value), 0.0), 1.0), 4)
    except (TypeError, ValueError):
        raise jev.JevError("Jev returned probabilities that are not numbers.")


def combine(response, options):
    """
    The exclusion question's answer: (probabilities {E1…, none: p}, p_exclude = 1 - p(none), the most probable
    criterion key).
    """
    keys = [option["key"] for option in options]
    answer = response["answers"].get(screening_requests.EXCLUSION_QUESTION)
    given = answer.get("probabilities") if isinstance(answer, dict) else None
    if not isinstance(given, dict):
        raise jev.JevError("Jev did not answer the exclusion question.")
    probabilities = {key: _probability(given.get(key, 0.0)) for key in keys + [NONE]}
    p_exclude = round(min(max(1.0 - probabilities[NONE], 0.0), 1.0), 4)
    return probabilities, p_exclude, max(keys, key=lambda key: probabilities[key])


def combine_inclusion(response, options):
    """The inclusion questions' answers: {I1…: p(meets)}, the probability of yes of each criterion's question."""
    probabilities = {}
    for option in options:
        answer = response["answers"].get(screening_requests.inclusion_question_id(option["key"]))
        value = answer.get(INCLUSION_QUESTION) if isinstance(answer, dict) else None
        if value is None:
            raise jev.JevError(f"Jev did not answer the question about {option['key']}.")
        probabilities[option["key"]] = _probability(value)
    return probabilities


def decide_inclusion(probabilities, thresholds, rule=INCLUDE_ALL):
    """
    (accepted, deciding criterion). Rule "all": accepted when every criterion's p(meets) reaches its own threshold;
    the deciding criterion is the one closest to failing (or the most short of its threshold). Rule "any": accepted
    when one criterion reaches its threshold; the deciding criterion is the one furthest above its threshold (or the
    closest to it).
    """
    pick = max if rule == INCLUDE_ANY else min
    deciding = pick(probabilities, key=lambda key: probabilities[key] - thresholds[key])
    return probabilities[deciding] >= thresholds[deciding], deciding


# Runs ---------------------------------------------------------------------------------------------------------------


def list_runs(review):
    return review.screening_runs.select_related("started_by", "reviewer")


def list_results(run, *, outcome=None):
    """
    Answers of a run, in screening order; ``outcome`` filters (excluded, passed, included, undecided, error,
    pending).
    """
    results = run.results.select_related("article", "run")
    if outcome:
        if outcome not in dict(ScreeningResult.OUTCOMES):
            raise ValidationError(f"outcome must be one of {sorted(dict(ScreeningResult.OUTCOMES))}.", field="outcome")
        results = results.filter(outcome=outcome)
    return results.order_by("pk")


def criteria_key(run, criteria_id):
    """The option key (E1, E2…) a criterion had in the run, or None."""
    return next((option["key"] for option in run.parameters.get("criteria", []) if option["id"] == criteria_id), None)


def get_run(review, run_id):
    try:
        return review.screening_runs.get(pk=run_id)
    except (ScreeningRun.DoesNotExist, ValueError, TypeError):
        raise NotFound(f"Screening run {run_id!r} not found.")


def _clean_model(actor, model):
    """The model for the run: the actor's default, or another one Jev lists for the actor's key."""
    default = integrations.get_jev(actor).model or jev.DEFAULT_MODEL
    model = (model or "").strip() or default
    check_length(model, 100, field="model")
    if model != default and model not in {card["name"] for card in integrations.test_jev(actor)}:
        raise ValidationError(f"Jev does not list the model {model!r} for your key.", field="model")
    return model


def _clean_request(review, phase, base, context, guidance, template, criteria_ids):
    """
    The criteria (sent, and the ids left out), context, guidance and request template of a run of ``phase``,
    checked. What is left out (None; a context field at a time) takes ``base``, the settings the run starts from.
    """
    options, skipped = clean_criteria(review, phase, base["criteria_ids"] if criteria_ids is None else criteria_ids)
    merged = default_context(review)
    merged.update({name: value for name, value in (base["context"] or {}).items() if value is not None})
    merged.update({name: value for name, value in (context or {}).items() if value is not None})
    context, guidance = _clean_context(merged, base["guidance"] if guidance is None else guidance)
    if template is None:
        template = base["template"]
    else:
        template = screening_requests.clean(phase, template)
    return options, skipped, context, guidance, template


def clean_scope(review, phase, statuses, source_id):
    """The statuses (see ``clean_statuses``) and the source of the studies sent; source "", 0 or None: all sources."""
    statuses = clean_statuses(statuses, phase)
    if source_id in ("", None, 0, "0"):
        return statuses, None
    if not review.sources.filter(pk=source_id).exists():
        raise NotFound(f"Source {source_id!r} not found in this review.")
    return statuses, int(source_id)


def _decide_settings(review, phase, options, base, threshold, thresholds):
    """The thresholds of a run (and the inclusion rule it follows), checked."""
    decide = {}
    if phase in (EXCLUSION, SCREEN):
        decide["threshold"] = clean_threshold(base["threshold"] if threshold is None else threshold)
    if phase in (INCLUSION, SCREEN):
        inclusion = [option for option in options if option["key"].startswith("I")]
        single = threshold if phase == INCLUSION else None  # in Screen with AI, threshold is the exclusion one
        decide["thresholds"] = clean_thresholds(inclusion, thresholds, single, base["thresholds"])
        decide["inclusion_rule"] = review.inclusion_rule
    elif _given_thresholds(thresholds):
        raise ValidationError(
            f"Per-criterion thresholds are for the inclusion criteria; {LABELS[phase]} has one threshold.",
            field="thresholds",
        )
    return decide


@transaction.atomic
def start_run(
    *,
    review,
    actor,
    reviewer_id,
    phase=EXCLUSION,
    model=None,
    context=None,
    guidance=None,
    template=None,
    threshold=None,
    thresholds=None,
    source_id=None,
    statuses=None,
    criteria_ids=None,
    defaults=False,
):
    """
    Check the settings, take the studies in scope and open a run of ``phase`` (exclusion, inclusion or screen);
    ``process_step`` does the work. The decisions are recorded as ``reviewer_id``; the calls use the actor's Jev key.
    Whatever is left out (None) takes the settings of the review's last run of that action, or Parsifal's defaults
    with ``defaults`` (see ``starting_settings``); a context field "" sends it empty, source_id "" or 0 means all
    sources. ``template``: the request sent about each study, as an object or its JSON text (see
    ``screening_requests``). ``criteria_ids``: the criteria sent. ``threshold``: the exclusion threshold (see
    ``clean_threshold``); inclusion has one per criterion (``thresholds``, see ``clean_thresholds``). ``statuses``
    picks the studies sent (codes U, R, A, D; see ``clean_statuses``).
    """
    phase = clean_phase(phase)
    integrations.jev_api_key(actor)  # a key the actor can use, before anything else
    reviewer = get_reviewer(review, actor, reviewer_id)
    base = starting_settings(review, phase, defaults=defaults)
    model = _clean_model(actor, base["model"] if model is None else model)
    options, skipped, context, guidance, template = _clean_request(
        review, phase, base, context, guidance, template, criteria_ids
    )
    decide = _decide_settings(review, phase, options, base, threshold, thresholds)
    statuses, source_id = clean_scope(
        review,
        phase,
        base["statuses"] if statuses is None else statuses,
        base["source_id"] if source_id is None else source_id,
    )
    articles = list(eligible_articles(review, statuses=statuses, source_id=source_id).values_list("pk", "status"))
    if not articles:
        raise ValidationError("There are no studies with these statuses in this scope.", field="statuses")

    # One run at a time per review: a run left behind (page closed mid-way) is closed now.
    discard_unfinished(review)

    parameters = {
        "context": context,
        "guidance": guidance,
        "criteria": options,
        "skipped_criteria": skipped,  # left out by choice, so a later run leaves them out too
        "template": template,
        **decide,
        "source_id": source_id,
        "statuses": statuses,
    }
    run = ScreeningRun.objects.create(
        review=review,
        reviewer=reviewer,
        started_by=actor,
        phase=phase,
        model=model,
        parameters=parameters,
        total=len(articles),
    )
    ScreeningResult.objects.bulk_create(
        ScreeningResult(run=run, article_id=pk, previous_status=status) for pk, status in articles
    )
    return run


def preview(
    *,
    review,
    actor,
    phase=EXCLUSION,
    model=None,
    context=None,
    guidance=None,
    template=None,
    source_id=None,
    statuses=None,
    criteria_ids=None,
    defaults=False,
    article_id=None,
):
    """
    The request a run with these settings (see ``start_run``) would send to Jev about one study, without sending
    anything: ``article_id``, or else the first study in scope with a title or abstract. Returns {"article",
    "request": {"model", "state", "questions"}}; ``model`` defaults to the run's and is not checked with Jev.
    """
    phase = clean_phase(phase)
    base = starting_settings(review, phase, defaults=defaults)
    options, _skipped, context, guidance, template = _clean_request(
        review, phase, base, context, guidance, template, criteria_ids
    )
    if article_id not in (None, ""):
        article = get_child(review.article_set, article_id, label="Article")
        study = state(article)
        if study is None:
            raise ValidationError("The study has no title or abstract to read.", field="article_id")
    else:
        statuses, source_id = clean_scope(
            review,
            phase,
            base["statuses"] if statuses is None else statuses,
            base["source_id"] if source_id is None else source_id,
        )
        article = study = None
        for candidate in eligible_articles(review, statuses=statuses, source_id=source_id).iterator():
            study = state(candidate)
            if study is not None:
                article = candidate
                break
        if article is None:
            raise ValidationError(
                "There are no studies with a title or abstract with these statuses in this scope.", field="statuses"
            )
    integration = integrations.get_jev(actor)
    model = (model or "").strip() or base["model"] or (integration.model if integration else "") or jev.DEFAULT_MODEL
    check_length(model, 100, field="model")
    request_state, questions = build_request(phase, template, options, context, guidance, study)
    return {"article": article, "request": {"model": model, "state": request_state, "questions": questions}}


def _close(run, status, error=""):
    run.results.filter(outcome=ScreeningResult.PENDING).delete()
    run.status = status
    run.error = error[:500]
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "error", "finished_at"])


def discard_unfinished(review, error=""):
    """Close the review's running runs as cancelled, without their remaining studies. Returns how many."""
    runs = list(review.screening_runs.filter(status=ScreeningRun.RUNNING))
    for run in runs:
        _close(run, ScreeningRun.CANCELLED, error)
    return len(runs)


def unfinished_run(review):
    """The review's run left half-way (page closed, connection lost, Jev unavailable), or None."""
    run = review.screening_runs.filter(status=ScreeningRun.RUNNING).select_related("reviewer").first()
    if run is None or not run.results.filter(outcome=ScreeningResult.PENDING).exists():
        return None
    return run


def is_active(run):
    """Whether a step ran a moment ago, i.e. some page or client is driving the run right now."""
    return run.last_step_at is not None and (timezone.now() - run.last_step_at).total_seconds() < ACTIVE_FOR


def _interrupt(run, error):
    """Keep the run (and its remaining studies) waiting to be continued, with the reason; it can be continued now."""
    run.error = str(error)[:500]
    run.last_step_at = None
    run.save(update_fields=["error", "last_step_at"])


def _ask(api_key, model, payload):
    """One study (runs in a worker thread: no database access here)."""
    try:
        return jev.evaluate(api_key, model=model, state=payload["state"], questions=payload["questions"])
    except jev.JevError as error:
        return error


def process_step(*, run, actor, size=STEP_SIZE):
    """
    Screen the next ``size`` studies of the run and record the outcome. Returns the results of this step. The calls
    to Jev happen outside any transaction; each study's outcome is then written in a short one.
    """
    try:
        size = int(size)
    except (TypeError, ValueError):
        raise ValidationError("size must be a number.", field="size")
    if not 1 <= size <= MAX_STEP_SIZE:
        raise ValidationError(f"size must be between 1 and {MAX_STEP_SIZE}.", field="size")
    if run.status != ScreeningRun.RUNNING:
        return []
    if run.phase not in ACTIONS:  # Retain with AI was removed
        _close(run, ScreeningRun.CANCELLED, f"{LABELS[run.phase]} was removed.")
        return []
    api_key = integrations.jev_api_key(actor)
    run.last_step_at = timezone.now()
    run.save(update_fields=["last_step_at"])
    pending = list(run.results.filter(outcome=ScreeningResult.PENDING).select_related("article", "run")[:size])
    if not pending:
        _close(run, ScreeningRun.FINISHED)
        return []

    parameters = run.parameters
    # Runs from before request templates were editable used the default.
    template = parameters.get("template") or screening_requests.default(run.phase)
    payloads = {}
    for result in pending:
        study = state(result.article)
        if study is not None:
            request_state, questions = build_request(
                run.phase, template, parameters["criteria"], parameters["context"], parameters["guidance"], study
            )
            payloads[result.pk] = {"state": request_state, "questions": questions}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pk: pool.submit(_ask, api_key, run.model, payload) for pk, payload in payloads.items()}
        responses = {pk: future.result() for pk, future in futures.items()}

    # Jev refused the key: nothing is recorded and the run waits until it is continued with a working key.
    fatal = next((r for r in responses.values() if isinstance(r, jev.JevError) and r.fatal), None)
    if fatal is not None:
        _interrupt(run, fatal)
        return []

    # Jev unreachable, rate limited or overloaded even after the client's retries: those studies stay pending and are
    # sent again by the next step. When no study of the step got through, the run waits instead of going on.
    # Errors about one study (e.g. too long) are recorded as that study's error.
    def unavailable(response):
        return isinstance(response, jev.JevError) and (
            response.status is None or response.status in jev.RETRY_STATUSES
        )

    recorded = []
    for result in pending:
        response = responses.get(result.pk)
        if not unavailable(response):
            _record(run, result, response)
            recorded.append(result)
    if responses and not recorded:
        _interrupt(run, next(r for r in responses.values() if unavailable(r)))
        return []
    if run.error:
        run.error = ""
        run.save(update_fields=["error"])
    if not run.results.filter(outcome=ScreeningResult.PENDING).exists():
        _close(run, ScreeningRun.FINISHED)
    return recorded


@transaction.atomic
def _record(run, result, response):
    result.processed_at = timezone.now()
    if response is None:
        result.outcome = ScreeningResult.ERROR
        result.error = "The study has no title or abstract to read."
    elif isinstance(response, jev.JevError):
        result.outcome = ScreeningResult.ERROR
        result.error = str(response)[:500]
    else:
        try:
            apply = {EXCLUSION: _apply_exclusion, INCLUSION: _apply_inclusion, SCREEN: _apply_screen}[run.phase]
            apply(run, result, response)
        except jev.JevError as error:
            result.outcome = ScreeningResult.ERROR
            result.error = str(error)
    result.save()


def _apply_exclusion(run, result, response):
    probabilities, p_exclude, best = combine(response, run.parameters["criteria"])
    result.probabilities = probabilities
    result.p_exclude = p_exclude
    result.model = str(response.get("model") or run.model)[:100]
    if p_exclude < run.parameters["threshold"]:
        _pass(run, result, f"no exclusion criterion, p(exclude) = {p_exclude:.2f}")
        result.outcome = ScreeningResult.PASSED
    elif _reject(run, result, best, f"{best}, p(exclude) = {p_exclude:.2f}"):
        result.outcome = ScreeningResult.EXCLUDED
    else:
        _criterion_gone(result, best)


def _inclusion_answer(run, response):
    """
    The inclusion questions' answers of a run's response: (p(meets) of each criterion sent, its thresholds, whether
    the study is accepted, the deciding criterion, the rule, and a description of what was met).
    """
    options = [option for option in run.parameters["criteria"] if option["key"].startswith("I")]
    probabilities = combine_inclusion(response, options)
    # Runs from before the thresholds per criterion had one for all of them; runs from before the rule needed all.
    thresholds = run.parameters.get("thresholds") or dict.fromkeys(probabilities, run.parameters["threshold"])
    rule = run.parameters.get("inclusion_rule", INCLUDE_ALL)
    accepted, deciding = decide_inclusion(probabilities, thresholds, rule)
    meets = ", ".join(f"{key} {p_meets:.2f}" for key, p_meets in probabilities.items())
    if accepted and rule == INCLUDE_ANY:
        detail = f"meets {deciding}, and one inclusion criterion is enough — meets: {meets}"
    elif accepted:
        detail = f"meets every inclusion criterion — meets: {meets}"
    elif rule == INCLUDE_ANY:
        detail = (
            f"undecided, no inclusion criterion reaches its threshold (closest: {deciding} "
            f"{probabilities[deciding]:.2f} for {thresholds[deciding]:.2f}) — meets: {meets}"
        )
    else:
        detail = (
            f"undecided, {deciding} {probabilities[deciding]:.2f} below its threshold {thresholds[deciding]:.2f} — "
            f"meets: {meets}"
        )
    return probabilities, accepted, deciding, detail


def _apply_inclusion(run, result, response):
    probabilities, accepted, deciding, detail = _inclusion_answer(run, response)
    result.probabilities = probabilities
    result.p_include = probabilities[deciding]
    result.model = str(response.get("model") or run.model)[:100]
    if accepted:
        _accept(run, result, detail)
        result.outcome = ScreeningResult.INCLUDED
    else:
        _undecided(run, result, detail)
        result.outcome = ScreeningResult.UNDECIDED


def _apply_screen(run, result, response):
    """
    Screen with AI: exclusion first — a criterion that applies rejects the study even when it meets the inclusion
    criteria —, then inclusion accepts it, or it is left undecided.
    """
    exclusion = [option for option in run.parameters["criteria"] if option["key"].startswith("E")]
    excluding, p_exclude, best = combine(response, exclusion)
    meeting, accepted, deciding, detail = _inclusion_answer(run, response)
    result.probabilities = {**excluding, **meeting}
    result.p_exclude = p_exclude
    result.p_include = meeting[deciding]
    result.model = str(response.get("model") or run.model)[:100]
    if p_exclude >= run.parameters["threshold"]:
        if _reject(run, result, best, f"{best}, p(exclude) = {p_exclude:.2f} (inclusion: {detail})"):
            result.outcome = ScreeningResult.EXCLUDED
        else:
            _criterion_gone(result, best)
    elif accepted:
        _accept(run, result, f"{detail}; no exclusion criterion, p(exclude) = {p_exclude:.2f}")
        result.outcome = ScreeningResult.INCLUDED
    else:
        if result.previous_status in (Article.ACCEPTED, Article.REJECTED):
            _set_status(run, result, Article.UNCLASSIFIED)
        _decide(
            run, result, Article.UNCLASSIFIED, None, f"{detail}; no exclusion criterion, p(exclude) = {p_exclude:.2f}"
        )
        result.outcome = ScreeningResult.UNDECIDED


def _criterion_gone(result, key):
    result.outcome = ScreeningResult.ERROR
    result.error = f"Criterion {key} was deleted from the review during the run."


def _changeable(run, result):
    """
    The study, if the run may change its status: it was unclassified, or classified by the run's reviewer (rejected,
    in an exclusion run; accepted, in an inclusion run; either, in a screen run), when the run took it, and nobody
    changed it since. Duplicates and studies classified by someone else keep their status (the reviewer's decision is
    recorded all the same); an exclusion run never changes an accepted study, nor an inclusion run a rejected one.
    """
    if result.previous_status not in CHANGEABLE[run.phase]:
        return run.review.article_set.none()
    articles = run.review.article_set.filter(pk=result.article_id, status=result.previous_status)
    if result.previous_status != Article.UNCLASSIFIED:
        articles = articles.filter(updated_by=run.reviewer)
    return articles


def _set_status(run, result, status, criteria_id=None):
    """
    Give the study ``status`` when the run may change it, keeping in the result what undoing the run restores; the
    study's last change is the result's ``processed_at``, so that undoing can tell whether anyone changed it since.
    """
    articles = _changeable(run, result)
    before = articles.values("selection_criteria_id", "updated_by_id", "updated_at").first()
    if before is None:
        return
    articles.update(
        status=status, selection_criteria_id=criteria_id, updated_by=run.reviewer, updated_at=result.processed_at
    )
    result.status_set = status
    result.previous_criteria_id = before["selection_criteria_id"]
    result.previous_updated_by_id = before["updated_by_id"]
    result.previous_updated_at = before["updated_at"]


def decision_snapshot(decision):
    """A reviewer's decision as a result keeps it (``previous_decision``), from its values or None."""
    if decision is None:
        return None
    return {
        "status": decision["status"],
        "criteria_id": decision["selection_criteria_id"],
        "comments": decision["comments"],
        "decided_at": decision["decided_at"].isoformat() if decision["decided_at"] else None,
        "run_id": decision["run_id"],
    }


def _decide(run, result, status, criteria_id, detail):
    """Record the reviewer's decision, keeping in the result the one it replaces."""
    before = StudyDecision.objects.filter(
        article_id=result.article_id, user=run.reviewer, stage=StudyDecision.TITLE_ABSTRACT
    ).values("status", "selection_criteria_id", "comments", "decided_at", "run_id")
    result.previous_decision = decision_snapshot(before.first())
    decisions.record_decision(
        review=run.review,
        article_id=result.article_id,
        actor=run.reviewer,
        status=status,
        stage=StudyDecision.TITLE_ABSTRACT,
        criteria_id=criteria_id,
        comments=f"{LABELS[run.phase]} (run {run.pk}, {result.model}): {detail}.",
        run=run,
    )


def _reject(run, result, key, detail):
    """
    Exclusion (and Screen): record the reviewer's "rejected" decision with the criterion ``key``, and reject the study
    with it when the run may change its status (see ``_changeable``). False when the criterion is gone.
    """
    criteria_id = next(option["id"] for option in run.parameters["criteria"] if option["key"] == key)
    if not run.review.selectioncriteria_set.filter(pk=criteria_id).exists():
        return False
    result.selection_criteria_id = criteria_id
    _set_status(run, result, Article.REJECTED, criteria_id)
    _decide(run, result, Article.REJECTED, criteria_id, detail)
    return True


def _pass(run, result, detail):
    """
    Exclusion, no criterion applies: the reviewer's decision becomes "unclassified", and a study this reviewer had
    rejected goes back to unclassified.
    """
    if result.previous_status == Article.REJECTED:
        _set_status(run, result, Article.UNCLASSIFIED)
    _decide(run, result, Article.UNCLASSIFIED, None, detail)


def _accept(run, result, detail):
    """
    Inclusion (and Screen), the inclusion criteria are met: the reviewer's decision is "accepted", and so is the
    study when the run may change its status (see ``_changeable``).
    """
    _set_status(run, result, Article.ACCEPTED)
    _decide(run, result, Article.ACCEPTED, None, detail)


def _undecided(run, result, detail):
    """
    Inclusion, the inclusion criteria are not met: the reviewer's decision becomes "unclassified", and a study this
    reviewer had accepted goes back to unclassified. Include with AI never rejects.
    """
    if result.previous_status == Article.ACCEPTED:
        _set_status(run, result, Article.UNCLASSIFIED)
    _decide(run, result, Article.UNCLASSIFIED, None, detail)


def progress(run):
    """Counts of the run so far."""
    counts = run.results.aggregate(
        excluded=Count("pk", filter=Q(outcome=ScreeningResult.EXCLUDED)),
        passed=Count("pk", filter=Q(outcome=ScreeningResult.PASSED)),
        included=Count("pk", filter=Q(outcome=ScreeningResult.INCLUDED)),
        undecided=Count("pk", filter=Q(outcome=ScreeningResult.UNDECIDED)),
        failed=Count("pk", filter=Q(outcome=ScreeningResult.ERROR)),
    )
    counts["processed"] = sum(counts.values())
    return {"id": run.pk, "phase": run.phase, "status": run.status, "total": run.total, "error": run.error, **counts}


# What a result means for the study, in the statuses the study list has --------------------------------------------

# The reviewer's decision each answer records: the run gives the study this status when it may change it.
DECISIONS = {
    ScreeningResult.EXCLUDED: Article.REJECTED,
    ScreeningResult.PASSED: Article.UNCLASSIFIED,
    ScreeningResult.INCLUDED: Article.ACCEPTED,
    ScreeningResult.UNDECIDED: Article.UNCLASSIFIED,
}
STATUS_NAMES = dict(Article.ARTICLE_STATUS)


def result_status(result):
    """
    The status a run gave a study, as the study list names it — Rejected, Accepted or Unclassified (the reviewer's
    decision) —, or None when the study was not screened (pending, error).
    """
    return DECISIONS.get(result.outcome)


def kept_status(result):
    """
    The status the study kept instead of ``result_status``, when the run could not change it (it was classified by
    someone else, or the action does not decide it), or None. Known for the runs that keep what came before them.
    """
    decided = result_status(result)
    if decided is None or not result.run.undoable:
        return None
    status = result.status_set or result.previous_status
    return status if status != decided else None


# How likely a study is relevant, by the latest AI answer about it ---------------------------------------------------


def relevance(phase, p_exclude, p_include):
    """
    How likely a study is relevant (0–1), as a run of ``phase`` answered about it: exclusion, 1 − p(exclude);
    inclusion, the deciding criterion's p(meets); screen, the lower of the two; older retention runs, p(retain). None
    without an answer. It ranks the studies to read the most likely first; the decisions use the thresholds.
    """
    values = []
    if phase in (EXCLUSION, SCREEN) and p_exclude is not None:
        values.append(1 - p_exclude)
    if phase in (INCLUSION, SCREEN, RETENTION) and p_include is not None:
        values.append(p_include)
    return round(min(values), 2) if values else None


def _latest_answers(article):
    """The answers about ``article`` (a study or an OuterRef to it), the latest first."""
    answered = ScreeningResult.objects.filter(article=article).exclude(
        outcome__in=(ScreeningResult.PENDING, ScreeningResult.ERROR)
    )
    return answered.order_by("-processed_at", "-pk")


def with_relevance(articles):
    """
    ``articles`` with what the latest AI answer about each said: ``ai_phase``, ``ai_p_exclude``, ``ai_p_include``
    and ``ai_relevance`` (see ``relevance``; None for studies no run answered about), to show and sort by.
    """
    latest = _latest_answers(OuterRef("pk"))
    not_excluded = Value(1.0) - F("ai_p_exclude")
    return articles.annotate(
        ai_phase=Subquery(latest.values("run__phase")[:1]),
        ai_p_exclude=Subquery(latest.values("p_exclude")[:1]),
        ai_p_include=Subquery(latest.values("p_include")[:1]),
    ).annotate(
        ai_relevance=Case(
            When(ai_phase=EXCLUSION, then=not_excluded),
            When(ai_phase=SCREEN, then=Least(not_excluded, F("ai_p_include"))),
            When(ai_phase__in=(INCLUSION, RETENTION), then=F("ai_p_include")),
            default=None,
            output_field=FloatField(),
        )
    )


def article_relevance(article):
    """``relevance`` of one study: from ``with_relevance``'s annotations, or else looked up."""
    if not hasattr(article, "ai_phase"):
        latest = _latest_answers(article).values("run__phase", "p_exclude", "p_include").first()
        if latest is None:
            return None
        return relevance(latest["run__phase"], latest["p_exclude"], latest["p_include"])
    return relevance(article.ai_phase, article.ai_p_exclude, article.ai_p_include)
