"""
The control of AI screening runs (Exclude, Include and Retain with AI): what each one did and how much of it still
stands, undoing one, running one again with the same settings, and what a new run would rewrite before it starts.

Only the latest run of the review can be undone, so runs are undone one by one from the newest: once the latest is
undone, the run before it becomes the latest. Undoing a run takes back its evaluation where it still stands, then
deletes the run with its answers:

- the reviewer's decision, while it is still the run's (nobody replaced it since), goes back to the decision it
  replaced, or is removed when there was none;
- a study whose status the run changed, while nobody changed it since (the status the run gave it, the run's reviewer
  as its last editor, last changed by the run), goes back to its status, criterion and last editor from before.

Decisions replaced since and studies changed since stay as they are; other reviewers' decisions and the studies the
run did not change are never touched. What a run restores is what came before it, so undoing the runs from the newest
goes back step by step: a restored decision belongs again to the run that made it, and a restored study is again as
that run left it.

Only runs that kept what was there before them (``ScreeningRun.undoable``: those started since Parsifal does) can be
undone, never while a run of the review is being screened, and only by the main author or the run's own reviewer
(the same people who may start it).
"""

from django.db import transaction
from django.db.models import Count
from django.utils.dateparse import parse_datetime

from parsifal.apps.core.exceptions import Conflict, PermissionDenied, ValidationError
from parsifal.apps.reviews.models import Article, ScreeningResult, ScreeningRun, StudyDecision
from parsifal.apps.reviews.services import ai_screening

STATUS_NAMES = dict(Article.ARTICLE_STATUS)
# Results that did nothing: not screened yet, or Jev's answer could not be used.
NO_EFFECT = (ScreeningResult.PENDING, ScreeningResult.ERROR)
CHUNK = 500  # ids per query, under SQLite's limit of variables


# Runs ---------------------------------------------------------------------------------------------------------------


def busy_run(review):
    """The review's run being screened right now (a step ran a moment ago), or None."""
    running = review.screening_runs.filter(status=ScreeningRun.RUNNING)
    return next((run for run in running if ai_screening.is_active(run)), None)


def latest_run(review):
    """The review's newest run, the only one that can be undone, or None."""
    return review.screening_runs.order_by("-created_at", "-pk").first()


def standing(review):
    """{run id: how many of its decisions are still the reviewer's}, for the runs that have any."""
    rows = review.decisions.filter(run__isnull=False).order_by().values("run_id").annotate(n=Count("pk"))
    return {row["run_id"]: row["n"] for row in rows}


def undo_problem(review, actor, run, busy=None, latest=None):
    """
    Why ``actor`` cannot undo ``run`` now, as the error to raise, or None. ``busy``: see ``busy_run``; ``latest``: see
    ``latest_run`` (looked up when left out).
    """
    if actor.pk != review.author_id and run.reviewer_id != actor.pk:
        return PermissionDenied("Only the main author can undo a run made in the name of another reviewer.")
    if not run.undoable:
        return ValidationError(
            f"Run {run.pk} was made before Parsifal kept what each study was like before a run; it cannot be undone."
        )
    latest = latest or latest_run(review)
    if latest.pk != run.pk:
        return ValidationError(f"Only the latest run can be undone: undo run {latest.pk} first.")
    if busy is not None:
        return Conflict(
            f"Run {busy.pk} is being screened right now; runs can be undone once it stops (half a minute after its "
            "window is closed)."
        )
    return None


def controls(review, actor, runs):
    """
    {run id: {"standing": decisions still the run's (None for runs that cannot be undone), "latest": whether it is
    the review's newest run, "undo_problem": why the actor cannot undo it now, "" when it can}} for the AI runs window
    and the API.
    """
    counts, busy, latest = standing(review), busy_run(review), latest_run(review)
    rows = {}
    for run in runs:
        problem = undo_problem(review, actor, run, busy, latest)
        rows[run.pk] = {
            "standing": counts.get(run.pk, 0) if run.undoable else None,
            "latest": run.pk == latest.pk,
            "undo_problem": str(problem) if problem else "",
        }
    return rows


# Undo ---------------------------------------------------------------------------------------------------------------


def _plan(run):
    """
    What undoing the run does: (the results that did something, those whose change of status still stands, those
    whose decision still stands paired with that decision's id).
    """
    results = list(run.results.exclude(outcome__in=NO_EFFECT).order_by("pk"))
    decisions = dict(
        StudyDecision.objects.filter(run=run, user_id=run.reviewer_id, stage=StudyDecision.TITLE_ABSTRACT).values_list(
            "article_id", "pk"
        )
    )
    # The studies whose status the run changed, as they are now.
    now = {
        pk: rest
        for pk, *rest in Article.objects.filter(
            screening_results__run=run, screening_results__status_set__in=list(STATUS_NAMES)
        ).values_list("pk", "status", "updated_by_id", "updated_at")
    }
    statuses = [
        result
        for result in results
        if result.status_set
        and now.get(result.article_id) == [result.status_set, run.reviewer_id, result.processed_at]
    ]
    decided = [(result, decisions[result.article_id]) for result in results if result.article_id in decisions]
    return results, statuses, decided


def _summary(run, results, statuses, decided):
    back_to = {code: 0 for code in STATUS_NAMES}
    for result in statuses:
        back_to[result.previous_status] += 1
    removed = sum(1 for result, _decision_id in decided if result.previous_decision is None)
    summary = {
        "run_id": run.pk,
        "phase": run.phase,
        "reviewer_id": run.reviewer_id,
        "reviewer": run.reviewer.username,
        "screened": len(results),
        "statuses_restored": len(statuses),
        "back_to": {code: count for code, count in back_to.items() if count},
        # The run changed their status, and so did someone since: they keep the newer one.
        "statuses_kept": sum(1 for result in results if result.status_set) - len(statuses),
        "decisions_restored": len(decided) - removed,
        "decisions_removed": removed,
        # The reviewer's decisions on them were replaced since: those stay.
        "decisions_kept": len(results) - len(decided),
    }
    summary["message"] = undo_message(summary)
    return summary


def _plural(count, one, many):
    return f"{count} {one if count == 1 else many}"


def undo_message(summary, done=False):
    """What undoing a run does (or, ``done``, did) in a few sentences; ``summary``: see ``undo_preview``."""

    def verb(count, now, then):  # now: (singular, plural)
        return then if done else now[count != 1]

    reviewer = summary["reviewer"]
    parts = []
    count = summary["statuses_restored"]
    if count:
        back_to = ", ".join(f"{n} {STATUS_NAMES[code].lower()}" for code, n in summary["back_to"].items())
        studies = _plural(count, "study", "studies")
        parts.append(
            f"{studies} {verb(count, ('goes', 'go'), 'went')} back to the status from before the run ({back_to})"
        )
    count = summary["decisions_restored"]
    if count:
        decisions = _plural(count, "decision", "decisions")
        parts.append(
            f"{decisions} of {reviewer} {verb(count, ('goes', 'go'), 'went')} back to the "
            f"{'one' if count == 1 else 'ones'} the run replaced"
        )
    count = summary["decisions_removed"]
    if count:
        decisions = _plural(count, "decision", "decisions")
        removed = verb(count, ("is", "are"), "was" if count == 1 else "were")
        parts.append(f"{decisions} of {reviewer} {removed} removed (there was none before)")
    start = f"Run {summary['run_id']} was undone" if done else f"Undoing run {summary['run_id']}"
    text = f"{start}: " + ("; ".join(parts) if parts else "nothing of it stands any more") + "."
    count = summary["statuses_kept"]
    if count:
        keep = verb(count, ("keeps the newer status", "keep the newer status"), "kept the newer status")
        studies = _plural(count, "study", "studies")
        text += f" {studies} whose status changed again since the run {keep}."
    count = summary["decisions_kept"]
    if count:
        stay = verb(count, ("stays", "stay"), "stayed")
        text += f" {_plural(count, 'decision', 'decisions')} of {reviewer} replaced since the run {stay}."
    return text + f" The run and its answers {'were' if done else 'are'} deleted."


def undo_preview(*, review, actor, run_id):
    """
    What undoing the run would do, without doing it: {"run_id", "phase", "reviewer_id", "reviewer", "screened"
    (studies it evaluated), "statuses_restored", "back_to" ({status: studies}), "statuses_kept" (changed again
    since: left as they are), "decisions_restored", "decisions_removed", "decisions_kept" (replaced since: left as
    they are), "message"}.
    """
    run = ai_screening.get_run(review, run_id)
    problem = undo_problem(review, actor, run, busy_run(review))
    if problem:
        raise problem
    return _summary(run, *_plan(run))


def _chunks(ids):
    ids = list(ids)
    for start in range(0, len(ids), CHUNK):
        end = start + CHUNK
        yield ids[start:end]


@transaction.atomic
def undo_run(*, review, actor, run_id):
    """
    Undo the run where its evaluation still stands and delete it (see the module). Returns what ``undo_preview``
    returns, with the message saying what was done.
    """
    run = ai_screening.get_run(review, run_id)
    problem = undo_problem(review, actor, run, busy_run(review))
    if problem:
        raise problem
    results, statuses, decided = _plan(run)
    summary = _summary(run, results, statuses, decided)
    summary["message"] = undo_message(summary, done=True)
    for result in statuses:
        Article.objects.filter(pk=result.article_id).update(
            status=result.previous_status,
            selection_criteria_id=result.previous_criteria_id,
            updated_by_id=result.previous_updated_by_id,
            updated_at=result.previous_updated_at,
        )
    criteria = set(review.selectioncriteria_set.values_list("pk", flat=True))
    runs = set(review.screening_runs.exclude(pk=run.pk).values_list("pk", flat=True))
    removed = []
    for result, decision_id in decided:
        before = result.previous_decision
        if before is None:
            removed.append(decision_id)
            continue
        StudyDecision.objects.filter(pk=decision_id).update(
            status=before["status"],
            selection_criteria_id=before["criteria_id"] if before["criteria_id"] in criteria else None,
            comments=before["comments"],
            decided_at=parse_datetime(before["decided_at"]),
            run_id=before["run_id"] if before["run_id"] in runs else None,
        )
    for ids in _chunks(removed):
        StudyDecision.objects.filter(pk__in=ids).delete()
    run.delete()
    return summary


# Run again ----------------------------------------------------------------------------------------------------------


def rerun_settings(review, run):
    """The settings of a new run like ``run`` (see ``ai_screening.run_settings``)."""
    return ai_screening.run_settings(review, run)


def _changed_settings(review, run, changes):
    settings = rerun_settings(review, run)
    changes = {name: value for name, value in changes.items() if value is not None}
    if "threshold" in changes and "thresholds" not in changes and run.phase == ai_screening.INCLUSION:
        settings["thresholds"] = None  # one threshold for every inclusion criterion
    settings.update(changes)
    return settings


def rerun(*, review, actor, run_id, **changes):
    """
    Start a new run like ``run_id`` (see ``rerun_settings``), with ``changes`` to its settings (``start_run``'s
    arguments; None keeps the run's). ``process_step`` does the work.
    """
    run = ai_screening.get_run(review, run_id)
    settings = _changed_settings(review, run, changes)
    if settings["source_id"] is None:
        settings["source_id"] = ""  # all sources, as the run, not the latest run's source
    return ai_screening.start_run(review=review, actor=actor, **settings)


# Before starting ----------------------------------------------------------------------------------------------------


def _classified_name(phase):
    statuses = sorted(ai_screening.CHANGEABLE[phase] - {Article.UNCLASSIFIED})
    return " or ".join(STATUS_NAMES[code].lower() for code in statuses)


def impact(*, review, actor, reviewer_id=None, phase=None, statuses=None, source_id=None, run_id=None, defaults=False):
    """
    What a new run would rewrite, to confirm before starting it: of the studies it sends, how many have a decision of
    its reviewer (which the run replaces) and how many that reviewer classified with a status the run may change.
    What is left out takes the settings the run starts from (``ai_screening.starting_settings``), or with ``run_id``
    those of that run, done again (see ``rerun``). Returns {"phase", "reviewer_id", "reviewer", "studies",
    "decisions", "classified", "confirm" (some is not zero), "message"}.
    """
    if run_id not in (None, ""):
        run = ai_screening.get_run(review, run_id)
        changes = {"reviewer_id": reviewer_id, "statuses": statuses, "source_id": source_id}
        settings = _changed_settings(review, run, changes)
    else:
        settings = ai_screening.starting_settings(review, phase, defaults=defaults)
        settings["reviewer_id"] = reviewer_id  # never someone else's by default: whoever the run is made as
        settings.update(
            {
                name: value
                for name, value in {"statuses": statuses, "source_id": source_id}.items()
                if value is not None
            }
        )
    reviewer_id, phase = settings["reviewer_id"], settings["phase"]
    statuses, source_id = settings["statuses"], settings["source_id"]
    phase = ai_screening.clean_phase(phase)
    reviewer = ai_screening.get_reviewer(review, actor, reviewer_id)
    statuses, source_id = ai_screening.clean_scope(review, phase, statuses, source_id)
    articles = ai_screening.eligible_articles(review, statuses=statuses, source_id=source_id)
    decisions = articles.filter(decisions__user=reviewer, decisions__stage=StudyDecision.TITLE_ABSTRACT).count()
    classified = articles.filter(
        status__in=ai_screening.CHANGEABLE[phase] - {Article.UNCLASSIFIED}, updated_by=reviewer
    ).count()
    studies = articles.count()
    sends = _plural(studies, "study", "studies")
    if decisions or classified:
        parts = []
        if decisions:
            parts.append(f"rewrites {_plural(decisions, 'decision', 'decisions')} of {reviewer.username}")
        if classified:
            parts.append(
                f"may change the status of {_plural(classified, 'study', 'studies')} {reviewer.username} "
                f"{_classified_name(phase)}"
            )
        message = (
            f"This run sends {sends} and {' and '.join(parts)}. While it is the latest run, it can be undone in AI "
            "runs."
        )
    else:
        message = f"This run sends {sends}; {reviewer.username} has no decisions on them yet."
    return {
        "phase": phase,
        "reviewer_id": reviewer.pk,
        "reviewer": reviewer.username,
        "studies": studies,
        "decisions": decisions,
        "classified": classified,
        "confirm": bool(decisions or classified),
        "message": message,
    }
