import json

from parsifal_cli import screening
from parsifal_cli.client import ApiClient
from parsifal_cli.config import Settings
from tests.conftest import invoke

RUN = {
    "id": 3,
    "phase": "exclusion",
    "status": "running",
    "model": "jev-1.13.0",
    "total": 2,
    "processed": 0,
    "excluded": 0,
    "passed": 0,
    "included": 0,
    "undecided": 0,
    "failed": 0,
    "error": "",
    "started_by": "alice",
    "created_at": "2026-10-18T00:00:00Z",
    "finished_at": None,
}


def progressed(**changes):
    return dict(RUN, **changes)


def routes(fake_api):
    fake_api.route("POST", "/api/v1/reviews/7/ai-screening/runs", 201, dict(RUN, parameters={"threshold": 0.95}))
    fake_api.route("GET", "/api/v1/reviews/7/ai-screening/runs/3", 200, dict(RUN, parameters={}))
    fake_api.route_many(
        "POST",
        "/api/v1/reviews/7/ai-screening/runs/3/step",
        {"run": progressed(processed=1, excluded=1), "results": [{"article_id": 1, "outcome": "excluded"}]},
        {"run": progressed(status="finished", processed=2, excluded=1, passed=1), "results": []},
    )


def bodies(fake_api, method, path):
    return [json.loads(r.content or b"null") for r in fake_api.requests if (r.method, r.url.path) == (method, path)]


def test_cli_run_starts_and_screens_to_the_end(runner, fake_api):
    routes(fake_api)
    result = invoke(
        runner,
        [
            "ai-screening",
            "run",
            "--review",
            "7",
            "--threshold",
            "0.95",
            "--guidance",
            "Be strict.",
            "--statuses",
            "R",
            "--statuses",
            "A",
            "--step-size",
            "10",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Run 3: 2 studies to screen." in result.output
    assert "1/2 screened · 1 rejected · 0 passed · 0 errors" in result.output
    assert '"status": "finished"' in result.output
    assert bodies(fake_api, "POST", "/api/v1/reviews/7/ai-screening/runs") == [
        {"guidance": "Be strict.", "threshold": 0.95, "statuses": ["R", "A"]}
    ]
    assert bodies(fake_api, "POST", "/api/v1/reviews/7/ai-screening/runs/3/step") == [{"size": 10}, {"size": 10}]


def test_cli_run_continues_a_run(runner, fake_api):
    routes(fake_api)
    result = invoke(runner, ["ai-screening", "run", "--review", "7", "--run", "3"])
    assert result.exit_code == 0, result.output
    assert not bodies(fake_api, "POST", "/api/v1/reviews/7/ai-screening/runs")
    assert bodies(fake_api, "POST", "/api/v1/reviews/7/ai-screening/runs/3/step")[0] == {"size": 25}


def test_cli_run_reports_api_errors(runner, fake_api):
    fake_api.route(
        "POST",
        "/api/v1/reviews/7/ai-screening/runs",
        422,
        {"detail": "Add your Jev API key", "code": "validation_error"},
    )
    result = invoke(runner, ["ai-screening", "run", "--review", "7"])
    assert result.exit_code != 0
    assert "Add your Jev API key" in result.output


def test_drive_stops_at_the_time_budget(fake_api):
    routes(fake_api)
    client = ApiClient(Settings(url="http://testserver", token="pfl_x"), transport=fake_api.transport)
    ticks = iter([0, 0, 100])  # deadline set at 0 + 60; first check passes, second is past it
    seen = []
    run = screening.drive(
        client,
        7,
        run_id=3,
        max_seconds=60,
        clock=lambda: next(ticks),
        on_step=lambda r, _: seen.append(r["processed"]),
    )
    assert (run["status"], run["processed"], seen) == ("running", 1, [1])
    assert screening.progress_line(run) == "1/2 screened · 1 rejected · 0 passed · 0 errors"


def interrupted_routes(fake_api):
    fake_api.route("POST", "/api/v1/reviews/7/ai-screening/runs", 201, dict(RUN, parameters={}))
    fake_api.route("GET", "/api/v1/reviews/7/ai-screening/runs/3", 200, dict(RUN, parameters={}))
    fake_api.route(
        "POST",
        "/api/v1/reviews/7/ai-screening/runs/3/step",
        200,
        {"run": progressed(error="Jev rejected the API key. Update it in Settings → Integrations."), "results": []},
    )


def test_drive_stops_when_the_run_is_interrupted(fake_api):
    interrupted_routes(fake_api)
    client = ApiClient(Settings(url="http://testserver", token="pfl_x"), transport=fake_api.transport)
    run = screening.drive(client, 7, run_id=3)
    assert len(bodies(fake_api, "POST", "/api/v1/reviews/7/ai-screening/runs/3/step")) == 1  # no endless loop
    assert screening.interrupted(run).startswith("Jev rejected the API key")
    assert screening.interrupted(progressed(status="finished", error="x")) == ""


def test_cli_run_reports_an_interruption_and_how_to_continue(runner, fake_api):
    interrupted_routes(fake_api)
    result = invoke(runner, ["ai-screening", "run", "--review", "7"])
    assert result.exit_code == 1
    assert "Jev rejected the API key" in result.output
    assert "continue it with --run 3" in result.output


def test_ctrl_c_interrupts_without_cancelling(runner, fake_api, monkeypatch):
    routes(fake_api)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(screening, "drive", interrupt)
    result = invoke(runner, ["ai-screening", "run", "--review", "7"])
    assert result.exit_code == 1
    assert "parsifal ai-screening run --review 7 --run 3" in result.output
    assert not [r for r in fake_api.requests if r.url.path.endswith("/cancel")]


def test_cli_run_include_with_ai(runner, fake_api):
    inclusion = dict(RUN, phase="inclusion")
    fake_api.route("POST", "/api/v1/reviews/7/ai-screening/runs", 201, dict(inclusion, parameters={}))
    fake_api.route("GET", "/api/v1/reviews/7/ai-screening/runs/3", 200, dict(inclusion, parameters={}))
    fake_api.route(
        "POST",
        "/api/v1/reviews/7/ai-screening/runs/3/step",
        200,
        {"run": dict(inclusion, status="finished", processed=2, included=1, undecided=1), "results": []},
    )
    result = invoke(
        runner,
        [
            "ai-screening",
            "run",
            "--review",
            "7",
            "--reviewer-id",
            "4",
            "--phase",
            "inclusion",
            "--threshold",
            "0.95",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "2/2 screened · 1 accepted · 1 undecided · 0 errors" in result.output
    assert bodies(fake_api, "POST", "/api/v1/reviews/7/ai-screening/runs") == [
        {"reviewer_id": 4, "phase": "inclusion", "threshold": 0.95}
    ]


def test_progress_line_per_phase():
    assert screening.progress_line(progressed(processed=2, excluded=1, passed=1)) == (
        "2/2 screened · 1 rejected · 1 passed · 0 errors"
    )
    assert screening.progress_line(progressed(phase="inclusion", processed=2, included=2)) == (
        "2/2 screened · 2 accepted · 0 undecided · 0 errors"
    )
