"""
AI screening of study selection, in two phases. Jev reads the title, keywords and abstract of each study (nothing
else: no authors, venue or affiliations) and answers about the review's criteria:

- **Exclude with AI** (phase 1): which exclusion criterion, if any, the study meets. One is enough to reject it.
- **Include with AI** (phase 2): whether the study meets each inclusion criterion. All of them must be met to accept
  it.

Every run is made in the name of a **reviewer** chosen by whoever starts it (the main author may pick any member of
the review, anyone else only themselves), so one person can screen as several reviewers and compare them. A run
sends the studies with the chosen statuses (default: unclassified and rejected for exclusion, unclassified and
accepted for inclusion) and rewrites this reviewer's decisions: nothing is skipped because it was evaluated before, so
two reviewers can screen the same studies and be compared (Reviewer agreement).

A run records the reviewer's decision on every study it screens, but changes a study's **status** only when the
study is unclassified, or was rejected (exclusion) or accepted or rejected (inclusion) by this same reviewer.
Duplicates and studies classified by someone else keep their status.

Every question is asked in three option orders within the same request (Jev tends to favour the first option when
unsure) and the answers are averaged.

Exclusion: the exclusion criteria plus a "none" option go in one choice question. Because the probabilities of a
choice sum to 1, the probability that *some* criterion applies is ``1 - p(none)``, even when two criteria split it.
Then:

- ``1 - p(none) >= threshold``: the reviewer's decision is "rejected" with the most probable criterion, and the
  study is rejected with it (when the run may change its status).
- otherwise: the reviewer's decision is "unclassified" (no criterion applies) and the study stays, or goes back to,
  unclassified for the next phase (when the run may change its status).

Inclusion: one choice question per inclusion criterion, answered meets, not_met or unclear. Every criterion must be
met, so the lowest p(meets) decides (an average would let a criterion that is clearly met make up for one that is
not). Then:

- lowest ``p(meets) >= threshold``: the reviewer's decision is "accepted" (and the study is accepted).
- otherwise, some ``p(not_met) >= threshold``: "rejected" with that criterion as the reason.
- otherwise: "unclassified"; the title and abstract do not settle it, so it is left to the reviewers.

A run is driven in small steps (``process_step``) so that the page can show its progress, and every answer is kept
in ``ScreeningResult`` for audit. A run cannot be stopped; when it is interrupted (page closed, connection lost, Jev
refusing the key or unavailable) it keeps its remaining studies and is continued by calling ``process_step`` again,
with the parameters it started with. Starting a new run discards an unfinished one.
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
ACTIVE_FOR = 30  # seconds: a running run with a step this recent is being driven somewhere
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

EXCLUSION, INCLUSION = ScreeningRun.EXCLUSION, ScreeningRun.INCLUSION
LABELS = {EXCLUSION: "Exclude with AI", INCLUSION: "Include with AI"}

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
INCLUSION_TASK = (
    "Screening for a systematic review, phase 2 (inclusion), from the title, keywords and abstract of a study: does "
    "the study meet this inclusion criterion?"
)
INCLUSION_RULES = (
    "Choose meets only if the title, keywords or abstract explicitly support that the study meets the criterion.",
    "Choose not_met only if the title, keywords or abstract explicitly show that the study does not meet it.",
    "If the title, keywords and abstract do not give enough information to decide, choose unclear.",
)
MEETS, NOT_MET, UNCLEAR = "meets", "not_met", "unclear"
UNCLEAR_DESCRIPTION = "The title, keywords and abstract do not give enough information to decide."
# Inclusion: what happens to a study that is neither clearly in nor clearly out. Only "keep_undecided" exists: it
# stays unclassified for the reviewers (kept in the run so that a stricter rule can be added later).
RULE_KEEP_UNDECIDED = "keep_undecided"
SENT_FIELDS = ("title", "keywords", "abstract")

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
    phase = str(phase or EXCLUSION).strip().lower()
    if phase not in LABELS:
        raise ValidationError(f"phase must be {EXCLUSION} or {INCLUSION}.", field="phase")
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
    return inclusion_options(review) if phase == INCLUSION else exclusion_options(review)


def task_and_rules(phase):
    return (INCLUSION_TASK, INCLUSION_RULES) if phase == INCLUSION else (TASK, RULES)


def answer_descriptions(option):
    """The options of an inclusion criterion's question."""
    return {
        MEETS: f"The study meets the inclusion criterion: {option['description']}",
        NOT_MET: f"The study does not meet the inclusion criterion: {option['description']}",
        UNCLEAR: UNCLEAR_DESCRIPTION,
    }


def clean_statuses(statuses, phase=EXCLUSION):
    """
    The statuses of the studies to send: codes U, R, A, D; None means the phase's default (exclusion: rejected and
    unclassified; inclusion: unclassified and accepted).
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


def _clean_threshold(threshold):
    try:
        threshold = round(float(threshold), 4)
    except (TypeError, ValueError):
        raise ValidationError("The threshold must be a number.", field="threshold")
    if not MIN_THRESHOLD <= threshold <= MAX_THRESHOLD:
        raise ValidationError(f"The threshold must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}.", field="threshold")
    return threshold


# Request ------------------------------------------------------------------------------------------------------------


def instructions(context, guidance, phase=EXCLUSION):
    review = {}
    for name, _label, _limit in CONTEXT_FIELDS:
        value = context.get(name)
        if value and name == "research_questions":
            review[name] = [line.strip() for line in value.splitlines() if line.strip()]
        elif value:
            review[name] = value
    task, rules = task_and_rules(phase)
    body = {"review": review, "task": task, "rules": list(rules)}
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


def inclusion_question_ids(options):
    """{criterion key: the ids of its question in each order}, e.g. {"I1": ["inclusion_i1_1", …]}."""
    return {
        option["key"]: [f"inclusion_{option['key'].lower()}_{order}" for order in range(1, ORDERS + 1)]
        for option in options
    }


def _answer_orders():
    answers = [MEETS, NOT_MET, UNCLEAR]
    return [answers[shift:] + answers[:shift] for shift in range(ORDERS)]


def inclusion_questions(options, context, guidance):
    """One choice question per inclusion criterion (meets, not_met, unclear), in every order."""
    asked = {}
    ids = inclusion_question_ids(options)
    for option in options:
        body = dict(instructions(context, guidance, INCLUSION), criterion=f"{option['key']}: {option['description']}")
        descriptions = answer_descriptions(option)
        for question_id, order in zip(ids[option["key"]], _answer_orders()):
            asked[question_id] = {
                "type": "choice",
                "instructions": body,
                "criteria": {answer: descriptions[answer] for answer in order},
            }
    return asked


def phase_questions(phase, options, context, guidance):
    if phase == INCLUSION:
        return inclusion_questions(options, context, guidance)
    return questions(options, context, guidance)


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
    probabilities = _average(response, question_ids(options), keys + [NONE], "the exclusion question")
    p_exclude = round(min(max(1.0 - probabilities[NONE], 0.0), 1.0), 4)
    return probabilities, p_exclude, max(keys, key=lambda key: probabilities[key])


def combine_inclusion(response, options):
    """
    Average each inclusion criterion's answers over the orders asked. Returns (probabilities {key: {meets, not_met,
    unclear}}, the weakest criterion: lowest p(meets), the most clearly failed one: highest p(not_met)).
    """
    ids = inclusion_question_ids(options)
    probabilities = {
        option["key"]: _average(
            response, ids[option["key"]], [MEETS, NOT_MET, UNCLEAR], f"the question about {option['key']}"
        )
        for option in options
    }
    weakest = min(probabilities, key=lambda key: probabilities[key][MEETS])
    failed = max(probabilities, key=lambda key: probabilities[key][NOT_MET])
    return probabilities, weakest, failed


def _average(response, question_ids, keys, about):
    """Each key's probability averaged over the questions Jev answered."""
    totals = dict.fromkeys(keys, 0.0)
    answered = 0
    for question_id in question_ids:
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
        raise jev.JevError(f"Jev did not answer {about}.")
    return {key: round(total / answered, 4) for key, total in totals.items()}


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
    statuses=None,
    phase=EXCLUSION,
):
    """
    Check the settings, take the studies in scope and open a run of ``phase`` (exclusion or inclusion);
    ``process_step`` does the work. The decisions are recorded as ``reviewer_id``; the calls use the actor's Jev key
    and ``model`` (default: the actor's default model). Context fields left out (or None) take the review's values;
    an empty string sends the field empty. ``statuses`` picks the studies sent (codes U, R, A, D; default: see
    ``clean_statuses``).
    """
    phase = clean_phase(phase)
    integrations.jev_api_key(actor)  # a key the actor can use, before anything else
    reviewer = get_reviewer(review, actor, reviewer_id)
    model = _clean_model(actor, model)
    options = criteria_options(review, phase)
    if not options:
        raise ValidationError(f"The review has no {phase} criteria. Add them in Planning first.", field="criteria")
    merged = default_context(review)
    merged.update({name: value for name, value in (context or {}).items() if value is not None})
    context, guidance = _clean_context(merged, guidance)
    threshold = _clean_threshold(threshold)
    statuses = clean_statuses(statuses, phase)
    if source_id in ("", None):
        source_id = None
    elif not review.sources.filter(pk=source_id).exists():
        raise NotFound(f"Source {source_id!r} not found in this review.")
    articles = list(eligible_articles(review, statuses=statuses, source_id=source_id).values_list("pk", "status"))
    if not articles:
        raise ValidationError("There are no studies with these statuses in this scope.", field="statuses")

    # One run at a time per review: a run left behind (page closed mid-way) is closed now.
    for stale in review.screening_runs.filter(status=ScreeningRun.RUNNING):
        _close(stale, ScreeningRun.CANCELLED)

    parameters = {
        "context": context,
        "guidance": guidance,
        "criteria": options,
        "threshold": threshold,
        "source_id": int(source_id) if source_id else None,
        "statuses": statuses,
        "orders": ORDERS if phase == INCLUSION else len(_orders(options)),
    }
    if phase == INCLUSION:
        parameters["rule"] = RULE_KEEP_UNDECIDED
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


def _close(run, status, error=""):
    run.results.filter(outcome=ScreeningResult.PENDING).delete()
    run.status = status
    run.error = error[:500]
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "error", "finished_at"])


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
    api_key = integrations.jev_api_key(actor)
    run.last_step_at = timezone.now()
    run.save(update_fields=["last_step_at"])
    pending = list(run.results.filter(outcome=ScreeningResult.PENDING).select_related("article", "run")[:size])
    if not pending:
        _close(run, ScreeningRun.FINISHED)
        return []

    options = run.parameters["criteria"]
    asked = phase_questions(run.phase, options, run.parameters["context"], run.parameters["guidance"])
    payloads = {}
    for result in pending:
        article_state = state(result.article)
        if article_state is not None:
            payloads[result.pk] = {"state": article_state, "questions": asked}
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
            if run.phase == INCLUSION:
                _apply_inclusion(run, result, response)
            else:
                _apply_exclusion(run, result, response)
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


def _apply_inclusion(run, result, response):
    probabilities, weakest, failed = combine_inclusion(response, run.parameters["criteria"])
    threshold = run.parameters["threshold"]
    result.probabilities = probabilities
    result.p_include = probabilities[weakest][MEETS]
    result.p_exclude = probabilities[failed][NOT_MET]
    result.model = str(response.get("model") or run.model)[:100]
    meets = ", ".join(f"{key} {answers[MEETS]:.2f}" for key, answers in probabilities.items())
    if result.p_include >= threshold:
        _accept(run, result, f"meets every inclusion criterion — meets: {meets}")
        result.outcome = ScreeningResult.INCLUDED
    elif result.p_exclude >= threshold:
        if _reject(run, result, failed, f"{failed} not met, p(not met) = {result.p_exclude:.2f} — meets: {meets}"):
            result.outcome = ScreeningResult.EXCLUDED
        else:
            _criterion_gone(result, failed)
    else:
        _undecided(run, result, f"undecided, weakest {weakest} (meet {result.p_include:.2f}) — meets: {meets}")
        result.outcome = ScreeningResult.UNDECIDED


def _criterion_gone(result, key):
    result.outcome = ScreeningResult.ERROR
    result.error = f"Criterion {key} was deleted from the review during the run."


def _changeable(run, result):
    """
    The study, if the run may change its status: it was unclassified, or classified by the run's reviewer (rejected,
    in an exclusion run; accepted or rejected, in an inclusion run), when the run took it, and nobody changed it
    since. Duplicates and studies classified by someone else keep their status (the reviewer's decision is recorded
    all the same); an exclusion run never changes an accepted study.
    """
    changeable = {Article.UNCLASSIFIED, Article.REJECTED}
    if run.phase == INCLUSION:
        changeable.add(Article.ACCEPTED)
    if result.previous_status not in changeable:
        return run.review.article_set.none()
    articles = run.review.article_set.filter(pk=result.article_id, status=result.previous_status)
    if result.previous_status != Article.UNCLASSIFIED:
        articles = articles.filter(updated_by=run.reviewer)
    return articles


def _set_status(run, result, status, criteria_id=None):
    _changeable(run, result).update(
        status=status, selection_criteria_id=criteria_id, updated_by=run.reviewer, updated_at=timezone.now()
    )


def _decide(run, result, status, criteria_id, detail):
    decisions.record_decision(
        review=run.review,
        article_id=result.article_id,
        actor=run.reviewer,
        status=status,
        stage=StudyDecision.TITLE_ABSTRACT,
        criteria_id=criteria_id,
        comments=f"{LABELS[run.phase]} (run {run.pk}, {result.model}): {detail}.",
    )


def _reject(run, result, key, detail):
    """
    Record the reviewer's "rejected" decision with the criterion ``key``, and reject the study with it when the run
    may change its status (see ``_changeable``). False when the criterion is gone.
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
    """Inclusion, every criterion is met: the reviewer's decision is "accepted", and so is the study."""
    _set_status(run, result, Article.ACCEPTED)
    _decide(run, result, Article.ACCEPTED, None, detail)


def _undecided(run, result, detail):
    """
    Inclusion, neither clearly met nor clearly not met: the reviewer's decision becomes "unclassified", and a study
    this reviewer had accepted or rejected goes back to unclassified.
    """
    if result.previous_status in (Article.ACCEPTED, Article.REJECTED):
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
