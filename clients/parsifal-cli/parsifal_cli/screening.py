"""
Drive an "Exclude with AI", "Include with AI" or "Screen with AI" run to its end, as the study selection page does in
the browser: start a run (or pick up an existing one) and call the step operation until the run is no longer running.
A run cannot be stopped; when it is interrupted (Jev refusing the key or unavailable) it keeps its remaining studies
and ``run["error"]`` says why, and the same call with its id continues it. Shared by ``parsifal ai-screening run`` and
the ``parsifal_ai_screening_run`` MCP tool.
"""

import time

from parsifal_cli.operations import BY_ID

DEFAULT_STEP_SIZE = 64  # the API's largest: fewer round trips, the server sends them concurrently
START_PARAMS = tuple(param for param in BY_ID["ai_screening_start"].params if param.name != "review_id")


def drive(
    client,
    review_id,
    *,
    run_id=None,
    start=None,
    step_size=DEFAULT_STEP_SIZE,
    max_seconds=None,
    on_step=None,
    clock=time.monotonic,
):
    """
    Returns the run as it stands when it is no longer running, when it is interrupted (``run["error"]``), or when
    ``max_seconds`` have passed; in the last two cases it keeps the status "running" and is continued with its id.
    ``on_step(run, results)`` is called after each step.
    """
    review_id = client.resolve_review(review_id)
    if run_id is None:
        run = client.call(BY_ID["ai_screening_start"], {"review_id": review_id, **(start or {})})
    else:
        run = client.call(BY_ID["ai_screening_runs_get"], {"review_id": review_id, "run_id": run_id})
    deadline = clock() + max_seconds if max_seconds else None
    while run["status"] == "running":
        if deadline is not None and clock() >= deadline:
            break
        step = client.call(
            BY_ID["ai_screening_step"], {"review_id": review_id, "run_id": run["id"], "size": step_size}
        )
        run = step["run"]
        if on_step is not None:
            on_step(run, step["results"])
        if run["status"] == "running" and run.get("error"):
            break
    return run


def interrupted(run):
    """Why a run that is still running stopped advancing (Jev refused the key or was unavailable), or ""."""
    return run.get("error", "") if run.get("status") == "running" else ""


def duration(seconds):
    """Seconds as m:ss, or h:mm:ss from an hour on."""
    seconds = max(0, round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class Stopwatch:
    """How long a run has been screened from here, and about how long is left at that pace."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.first_processed = None  # studies already screened when it started, known from the first step

    def step(self, run, results):
        """Pass it each step (``drive``'s ``on_step``)."""
        if self.first_processed is None:
            self.first_processed = run["processed"] - len(results)

    def text(self, run):
        elapsed = self.clock() - self.started
        text = f"{duration(elapsed)} elapsed"
        done = run["processed"] - (run["processed"] if self.first_processed is None else self.first_processed)
        left = run["total"] - run["processed"]
        if run.get("status") == "running" and done > 0 and left > 0:
            text += f" · about {duration(left * elapsed / done)} left"
        return text


def progress_line(run, stopwatch=None):
    if run.get("phase") == "inclusion":
        outcomes = f"{run['included']} accepted · {run['undecided']} undecided"
    elif run.get("phase") == "screen":
        outcomes = f"{run['excluded']} rejected · {run['included']} accepted · {run['undecided']} undecided"
    elif run.get("phase") == "retention":  # older runs of the removed Retain with AI
        outcomes = f"{run['included']} retained · {run['excluded']} not retained"
    else:
        outcomes = f"{run['excluded']} rejected · {run['passed']} passed"
    line = f"{run['processed']}/{run['total']} screened · {outcomes} · {run['failed']} errors"
    return f"{line} · {stopwatch.text(run)}" if stopwatch else line
