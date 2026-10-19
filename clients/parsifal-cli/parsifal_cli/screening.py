"""
Drive an "Exclude with AI" run to its end, as the study selection page does in the browser: start a run (or pick up
an existing one) and call the step operation until the run is no longer running. Shared by
``parsifal ai-screening run`` and the ``parsifal_ai_screening_run`` MCP tool.
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
    Returns the run as it stands when it stops running, or when ``max_seconds`` have passed (the run then keeps
    the status "running" and can be continued with its id). ``on_step(run, results)`` is called after each step.
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
    return run


def cancel(client, review_id, run_id):
    return client.call(BY_ID["ai_screening_cancel"], {"review_id": client.resolve_review(review_id), "run_id": run_id})


def progress_line(run):
    return (
        f"{run['processed']}/{run['total']} screened · {run['excluded']} rejected · {run['passed']} passed · "
        f"{run['failed']} errors"
    )
