"""
AI exclusion screening, phase 1 of study selection. Jev reads the title, keywords and abstract of each study and
says which exclusion criterion, if any, the study meets. Nothing else about the study is sent: no authors, venue or
affiliations.

Every run is made in the name of a **reviewer** chosen by whoever starts it (the main author may pick any member of
the review, anyone else only themselves), so one person can screen as several reviewers and compare them. A run
sends the unclassified studies plus those this reviewer rejected in an earlier run, and rewrites this reviewer's
decisions: nothing is skipped because it was evaluated before.

The exclusion criteria plus a "none" option go in one choice question, asked in three option orders within the
same request (Jev tends to favour the first option when unsure) and averaged. Because the probabilities of a choice
sum to 1, the probability that *some* criterion applies is ``1 - p(none)``, even when two criteria split it. Then:

- ``1 - p(none) >= threshold``: the reviewer's decision is "rejected" with the most probable criterion, and the
  study is rejected with it.
- otherwise: the reviewer's decision is "unclassified" (no criterion applies) and the study stays, or goes back to,
  unclassified for the next phase.

A run is driven in small steps (``process_step``) so that the page can show its progress, and every answer is kept
in ``ScreeningResult`` for audit.
"""

from concurrent.futures import ThreadPoolExecutor

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from parsifal.apps.accounts import services as integrations
from parsifal.apps.core import jev
from parsifal.apps.core.exceptions import NotFound, PermissionDenied, ValidationError
from parsifal.apps.reviews.models import Article, ReviewAgent, ScreeningResult, ScreeningRun, StudyDecision
from parsifal.apps.reviews.services import decisions
from parsifal.apps.reviews.services._common import check_length

DEFAULT_THRESHOLD = 0.9
MIN_THRESHOLD = 0.5
MAX_THRESHOLD = 0.99
STEP_SIZE = 8  # studies per step; one request each
MAX_STEP_SIZE = 50
WORKERS = 4  # concurrent requests to Jev within a step
ORDERS = 3  # option orders asked per study
NONE = "none"

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

# Fixed parts of the request: these define the method and are not editable.
TASK = (
    "Screening for a systematic review, phase 1 (exclusion only), from the title, keywords and abstract of a study: "
    "which exclusion criterion does the study meet?"
)
RULES = (
    "Choose a criterion only if the title, keywords or abstract explicitly support it.",
    "If several criteria apply, choose the one most clearly supported.",
    "If no criterion applies, or the title, keywords and abstract do not give enough information to decide, "
    "choose none.",
)
NONE_DESCRIPTION = (
    "No exclusion criterion is clearly supported by the title, keywords or abstract, or they do not give enough "
    "information to decide."
)
SENT_FIELDS = ("title", "keywords", "abstract")


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


def exclusion_options(review):
    """The review's exclusion criteria as the options of the question: E1, E2… in the order the review lists them."""
    return [
        {"key": f"E{index}", "id": criteria.pk, "description": criteria.description}
        for index, criteria in enumerate(review.get_exclusion_criterias(), start=1)
    ]


def _rejected_by(review, reviewer):
    """Studies still rejected as ``reviewer`` decided in an earlier run (nobody changed them since)."""
    excluded = ScreeningResult.objects.filter(
        run__review=review, run__reviewer=reviewer, outcome=ScreeningResult.EXCLUDED
    ).values("article_id")
    return Q(status=Article.REJECTED, updated_by=reviewer, pk__in=excluded)


def eligible_articles(review, *, reviewer, source_id=None):
    """
    What a run as ``reviewer`` sends: the unclassified studies plus those the reviewer rejected in an earlier run.
    Studies accepted, marked as duplicates or rejected by anyone else are never sent.
    """
    articles = review.article_set.filter(Q(status=Article.UNCLASSIFIED) | _rejected_by(review, reviewer))
    if source_id:
        articles = articles.filter(source_id=source_id)
    return articles.order_by("pk")


def scope_counts(review, reviewer=None):
    """How many studies a run would send, per scope: {"": all sources, "<source id>": n}."""
    if reviewer is None:
        articles = review.article_set.filter(status=Article.UNCLASSIFIED)
    else:
        articles = eligible_articles(review, reviewer=reviewer)
    counts = {"": articles.count()}
    for row in articles.order_by().values("source_id").annotate(n=Count("pk")):
        counts[str(row["source_id"])] = row["n"]
    return counts


def _clean_context(context, guidance):
    cleaned = {}
    for name, _label, limit in CONTEXT_FIELDS:
        cleaned[name] = check_length(str(context.get(name) or "").strip(), limit, field=name)
    return cleaned, check_length(str(guidance or "").strip(), GUIDANCE_LENGTH, field="guidance")


def _clean_threshold(threshold):
    try:
        threshold = round(float(threshold), 4)
    except (TypeError, ValueError):
        raise ValidationError("The threshold must be a number.", field="threshold")
    if not MIN_THRESHOLD <= threshold <= MAX_THRESHOLD:
        raise ValidationError(f"The threshold must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}.", field="threshold")
    return threshold


# Request ------------------------------------------------------------------------------------------------------------


def instructions(context, guidance):
    review = {}
    for name, _label, _limit in CONTEXT_FIELDS:
        value = context.get(name)
        if value and name == "research_questions":
            review[name] = [line.strip() for line in value.splitlines() if line.strip()]
        elif value:
            review[name] = value
    body = {"review": review, "task": TASK, "rules": list(RULES)}
    if guidance:
        body["guidance"] = guidance
    return body


def question_ids(options):
    return [f"exclusion_{index + 1}" for index in range(len(_orders(options)))]


def _orders(options):
    """Up to ORDERS distinct rotations of the options (criteria plus none), so every option changes position."""
    keys = [option["key"] for option in options] + [NONE]
    orders = []
    for index in range(ORDERS):
        shift = index * len(keys) // ORDERS
        order = keys[shift:] + keys[:shift]
        if order not in orders:
            orders.append(order)
    return orders


def questions(options, context, guidance):
    descriptions = {option["key"]: option["description"] for option in options}
    descriptions[NONE] = NONE_DESCRIPTION
    body = instructions(context, guidance)
    return {
        question_id: {"type": "choice", "instructions": body, "criteria": {key: descriptions[key] for key in order}}
        for question_id, order in zip(question_ids(options), _orders(options))
    }


def state(article):
    """What Jev reads about a study, or None when there is nothing to read."""
    values = {
        "title": article.title,
        "keywords": article.author_keywords or article.keywords,
        "abstract": article.abstract,
    }
    values = {name: value.strip() for name, value in values.items() if value and value.strip()}
    if "title" not in values and "abstract" not in values:
        return None
    return values


def combine(response, options):
    """
    Average each option's probability over the orders asked. Returns (probabilities, p_exclude, best criterion key).
    """
    keys = [option["key"] for option in options]
    totals = dict.fromkeys(keys + [NONE], 0.0)
    answered = 0
    for question_id in question_ids(options):
        answer = response["answers"].get(question_id)
        probabilities = answer.get("probabilities") if isinstance(answer, dict) else None
        if not isinstance(probabilities, dict):
            continue
        try:
            for key in totals:
                totals[key] += float(probabilities.get(key, 0.0))
        except (TypeError, ValueError):
            raise jev.JevError("Jev returned probabilities that are not numbers.")
        answered += 1
    if not answered:
        raise jev.JevError("Jev did not answer the exclusion question.")
    probabilities = {key: round(total / answered, 4) for key, total in totals.items()}
    p_exclude = round(min(max(1.0 - probabilities[NONE], 0.0), 1.0), 4)
    return probabilities, p_exclude, max(keys, key=lambda key: probabilities[key])


# Runs ---------------------------------------------------------------------------------------------------------------


def list_runs(review):
    return review.screening_runs.select_related("started_by", "reviewer")


def list_results(run, *, outcome=None):
    """Answers of a run, in screening order; ``outcome`` filters (excluded, passed, error, pending)."""
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


@transaction.atomic
def start_run(
    *,
    review,
    actor,
    reviewer_id,
    model=None,
    context=None,
    guidance="",
    threshold=DEFAULT_THRESHOLD,
    source_id=None,
):
    """
    Check the settings, take the studies in scope and open a run; ``process_step`` does the work. The decisions are
    recorded as ``reviewer_id``; the calls use the actor's Jev key and ``model`` (default: the actor's default model).
    Context fields left out (or None) take the review's values; an empty string sends the field empty.
    """
    integrations.jev_api_key(actor)  # a key the actor can use, before anything else
    reviewer = get_reviewer(review, actor, reviewer_id)
    model = _clean_model(actor, model)
    options = exclusion_options(review)
    if not options:
        raise ValidationError("The review has no exclusion criteria. Add them in Planning first.", field="criteria")
    merged = default_context(review)
    merged.update({name: value for name, value in (context or {}).items() if value is not None})
    context, guidance = _clean_context(merged, guidance)
    threshold = _clean_threshold(threshold)
    if source_id in ("", None):
        source_id = None
    elif not review.sources.filter(pk=source_id).exists():
        raise NotFound(f"Source {source_id!r} not found in this review.")
    articles = list(eligible_articles(review, reviewer=reviewer, source_id=source_id).values_list("pk", "status"))
    if not articles:
        raise ValidationError("There are no studies to screen in this scope.", field="source_id")

    # One run at a time per review: a run left behind (page closed mid-way) is closed now.
    for stale in review.screening_runs.filter(status=ScreeningRun.RUNNING):
        _close(stale, ScreeningRun.CANCELLED)

    run = ScreeningRun.objects.create(
        review=review,
        reviewer=reviewer,
        started_by=actor,
        model=model,
        parameters={
            "context": context,
            "guidance": guidance,
            "criteria": options,
            "threshold": threshold,
            "source_id": int(source_id) if source_id else None,
            "orders": len(_orders(options)),
        },
        total=len(articles),
    )
    ScreeningResult.objects.bulk_create(
        ScreeningResult(run=run, article_id=pk, previous_status=status) for pk, status in articles
    )
    return run


def _close(run, status, error=""):
    run.results.filter(outcome=ScreeningResult.PENDING).delete()
    run.status = status
    run.error = error[:500]
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "error", "finished_at"])


def cancel_run(*, run):
    if run.status == ScreeningRun.RUNNING:
        _close(run, ScreeningRun.CANCELLED)
    return run


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
    api_key = integrations.jev_api_key(actor)
    pending = list(run.results.filter(outcome=ScreeningResult.PENDING).select_related("article", "run")[:size])
    if not pending:
        _close(run, ScreeningRun.FINISHED)
        return []

    options = run.parameters["criteria"]
    asked = questions(options, run.parameters["context"], run.parameters["guidance"])
    payloads = {}
    for result in pending:
        article_state = state(result.article)
        if article_state is not None:
            payloads[result.pk] = {"state": article_state, "questions": asked}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pk: pool.submit(_ask, api_key, run.model, payload) for pk, payload in payloads.items()}
        responses = {pk: future.result() for pk, future in futures.items()}

    fatal = next((r for r in responses.values() if isinstance(r, jev.JevError) and r.fatal), None)
    if fatal is not None:
        _close(run, ScreeningRun.FAILED, str(fatal))
        return []

    for result in pending:
        _record(run, result, responses.get(result.pk))

    # Jev unreachable, rate limited or overloaded for every request of the step, even after the client's retries:
    # stop instead of burning through the rest of the studies. Errors about one study (e.g. too long) do not count.
    unavailable = [
        r
        for r in responses.values()
        if isinstance(r, jev.JevError) and (r.status is None or r.status in jev.RETRY_STATUSES)
    ]
    if responses and len(unavailable) == len(responses):
        _close(run, ScreeningRun.FAILED, str(unavailable[-1]))
    elif not run.results.filter(outcome=ScreeningResult.PENDING).exists():
        _close(run, ScreeningRun.FINISHED)
    return pending


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
        options = run.parameters["criteria"]
        try:
            probabilities, p_exclude, best = combine(response, options)
        except jev.JevError as error:
            result.outcome = ScreeningResult.ERROR
            result.error = str(error)
        else:
            result.probabilities = probabilities
            result.p_exclude = p_exclude
            result.model = str(response.get("model") or run.model)[:100]
            if p_exclude < run.parameters["threshold"]:
                _pass(run, result)
                result.outcome = ScreeningResult.PASSED
            elif _reject(run, result, best):
                result.outcome = ScreeningResult.EXCLUDED
            else:
                result.outcome = ScreeningResult.ERROR
                result.error = f"Criterion {best} was deleted from the review during the run."
    result.save()


def _unchanged(run, result):
    """The study, if nobody changed its status since the run took it (else it is left as it is)."""
    articles = run.review.article_set.filter(pk=result.article_id, status=result.previous_status)
    if result.previous_status == Article.REJECTED:
        articles = articles.filter(updated_by=run.reviewer)
    return articles


def _decide(run, result, status, criteria_id, comments):
    decisions.record_decision(
        review=run.review,
        article_id=result.article_id,
        actor=run.reviewer,
        status=status,
        stage=StudyDecision.TITLE_ABSTRACT,
        criteria_id=criteria_id,
        comments=f"Exclude with AI (run {run.pk}, {result.model}): {comments}, p(exclude) = {result.p_exclude:.2f}.",
    )


def _reject(run, result, key):
    """
    Reject the study as the run's reviewer, with the criterion ``key``. A study someone else classified while the
    run was going keeps its status (the reviewer's decision is still recorded). False when the criterion is gone.
    """
    criteria_id = next(option["id"] for option in run.parameters["criteria"] if option["key"] == key)
    if not run.review.selectioncriteria_set.filter(pk=criteria_id).exists():
        return False
    result.selection_criteria_id = criteria_id
    _unchanged(run, result).update(
        status=Article.REJECTED, selection_criteria_id=criteria_id, updated_by=run.reviewer, updated_at=timezone.now()
    )
    _decide(run, result, Article.REJECTED, criteria_id, key)
    return True


def _pass(run, result):
    """
    No criterion applies: the reviewer's decision becomes "unclassified", and a study this reviewer had rejected in
    an earlier run goes back to unclassified.
    """
    if result.previous_status == Article.REJECTED:
        _unchanged(run, result).update(
            status=Article.UNCLASSIFIED, selection_criteria=None, updated_by=run.reviewer, updated_at=timezone.now()
        )
    _decide(run, result, Article.UNCLASSIFIED, None, "no exclusion criterion")


def progress(run):
    """Counts of the run so far."""
    counts = run.results.aggregate(
        excluded=Count("pk", filter=Q(outcome=ScreeningResult.EXCLUDED)),
        passed=Count("pk", filter=Q(outcome=ScreeningResult.PASSED)),
        failed=Count("pk", filter=Q(outcome=ScreeningResult.ERROR)),
    )
    counts["processed"] = counts["excluded"] + counts["passed"] + counts["failed"]
    return {"id": run.pk, "status": run.status, "total": run.total, "error": run.error, **counts}
