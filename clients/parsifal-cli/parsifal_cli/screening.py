"""
Drive an "Exclude with AI" or "Include with AI" run to its end, as the study selection page does in the browser:
start a run (or pick up an existing one) and call the step operation until the run is no longer running. A run
cannot be stopped; when it is interrupted (Jev refusing the key or unavailable) it keeps its remaining studies and
``run["error"]`` says why, and the same call with its id continues it. Shared by ``parsifal ai-screening run`` and
the ``parsifal_ai_screening_run`` MCP tool.
"""

import time

from parsifal_cli.operations import BY_ID

DEFAULT_STEP_SIZE = 25
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


def progress_line(run):
    if run.get("phase") == "inclusion":
        outcomes = f"{run['included']} accepted · {run['excluded']} rejected · {run['undecided']} undecided"
    else:
        outcomes = f"{run['excluded']} rejected · {run['passed']} passed"
    return f"{run['processed']}/{run['total']} screened · {outcomes} · {run['failed']} errors"
