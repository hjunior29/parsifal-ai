"""The ``parsifal`` command: commands are generated from the operation registry."""

import inspect
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import typer

from parsifal_cli import __version__, config
from parsifal_cli.client import EXIT_ERROR, ApiClient, ApiError, ConnectionFailed, read_text_argument
from parsifal_cli.operations import BOOL, FILE, FLOAT, INT, LIST_INT, LIST_STR, OPERATIONS, TEXT
from parsifal_cli.output import error, render

PYTHON_TYPES = {INT: int, FLOAT: float, BOOL: bool, LIST_INT: list[int], LIST_STR: list[str], TEXT: str}


@dataclass
class State:
    url: str | None = None
    token: str | None = None
    profile: str | None = None
    json: bool = False
    transport: object = None  # injected by tests

    def client(self):
        settings = config.resolve(self.url, self.token, self.profile)
        return ApiClient(settings, transport=self.transport)


state = State()

app = typer.Typer(
    name="parsifal",
    help=(
        "Command-line client for a Parsifal instance. "
        "Set PARSIFAL_URL and PARSIFAL_TOKEN or use `parsifal config set`."
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.callback()
def root(
    url: str = typer.Option(None, "--url", envvar=config.ENV_URL, help="Server URL, e.g. http://localhost:8000."),
    token: str = typer.Option(None, "--token", envvar=config.ENV_TOKEN, help="API token (pfl_...)."),
    profile: str = typer.Option(None, "--profile", envvar=config.ENV_PROFILE, help="Profile from the config file."),
    json_output: bool = typer.Option(False, "--json", help="Always print JSON (default when not a terminal)."),
):
    state.url, state.token, state.profile, state.json = url, token, profile, json_output


# ---------------------------------------------------------------------------------------------------------------------
# Static commands
# ---------------------------------------------------------------------------------------------------------------------


@app.command()
def version():
    """Print the client version."""
    typer.echo(__version__)


@app.command()
def docs():
    """Print the review workflow guide (planning → conducting → reporting) for agents and humans."""
    typer.echo(resources.files("parsifal_cli").joinpath("data/workflow.md").read_text(encoding="utf-8"))


config_app = typer.Typer(help="Manage connection profiles stored in the config file.", no_args_is_help=True)
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show():
    """Show the effective settings (token masked) and the config file location."""
    settings = config.resolve(state.url, state.token, state.profile)
    render(
        {
            "profile": settings.profile,
            "url": settings.url,
            "token": config.mask(settings.token),
            "config_file": str(config.config_path()),
        },
        state.json,
    )


@config_app.command("set")
def config_set(
    url: str = typer.Option(None, help="Server URL."),
    token: str = typer.Option(None, help="API token."),
    profile: str = typer.Option("default", help="Profile name."),
):
    """Save URL and/or token into a profile of the config file."""
    if not url and not token:
        raise typer.BadParameter("Provide --url and/or --token.")
    profiles = config.load_profiles()
    values = dict(profiles.get(profile, {}))
    if url:
        values["url"] = url
    if token:
        values["token"] = token
    profiles[profile] = values
    config.save_profiles(profiles)
    typer.echo(f"Saved profile '{profile}' to {config.config_path()}")


# ---------------------------------------------------------------------------------------------------------------------
# Generated commands
# ---------------------------------------------------------------------------------------------------------------------

_groups = {}


def _group_app(group):
    """Return (creating if needed) the nested Typer app for a group path such as ("quality", "answer")."""
    if group == ():
        return app
    if group not in _groups:
        parent = _group_app(group[:-1])
        sub = typer.Typer(help=f"{group[-1].replace('-', ' ').capitalize()} commands.", no_args_is_help=True)
        parent.add_typer(sub, name=group[-1])
        _groups[group] = sub
    return _groups[group]


def _make_handler(operation):
    def handler(**kwargs):
        all_pages = kwargs.pop("all", False)
        limit = kwargs.pop("limit", None)
        offset = kwargs.pop("offset", None)
        output = kwargs.pop("output", None)
        yes = kwargs.pop("yes", False)
        if operation.destructive and not yes and sys.stdin.isatty() and sys.stdout.isatty():
            typer.confirm(f"Run `{operation.cli_name}`? This cannot be undone.", abort=True)
        values = {}
        for param in operation.params:
            value = kwargs.get(param.name)
            if param.type == TEXT:
                try:
                    value = read_text_argument(value)
                except OSError as exc:
                    error(f"Cannot read --{param.option}: {exc.strerror or exc} ({getattr(exc, 'filename', '')})")
                    raise typer.Exit(code=EXIT_ERROR)
            if param.kind == FILE and value is not None:
                value = str(value)
            values[param.name] = value
        client = state.client()
        try:
            result = client.call(operation, values, all_pages=all_pages, limit=limit, offset=offset)
        except (ApiError, ConnectionFailed) as exc:
            error(str(exc))
            raise typer.Exit(code=exc.exit_code)
        except OSError as exc:
            error(str(exc))
            raise typer.Exit(code=EXIT_ERROR)
        finally:
            client.close()
        if operation.download:
            _write_download(result, output)
            return
        render(result, state.json)

    parameters = []
    annotations = {}
    for param in operation.params:
        python_type = Path if param.kind == FILE else PYTHON_TYPES.get(param.type, str)
        if param.name == "review_id":
            python_type = str  # id or author/slug
        option_names = [f"--{param.option}"]
        if param.type == BOOL:
            option_names = [f"--{param.option}/--no-{param.option}"]
        default = typer.Option(... if param.required else None, *option_names, help=param.help or param.name)
        parameters.append(
            inspect.Parameter(param.name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=python_type)
        )
        annotations[param.name] = python_type

    extras = []
    if operation.paginated:
        extras += [
            ("limit", int, typer.Option(None, "--limit", help="Page size.")),
            ("offset", int, typer.Option(None, "--offset", help="Page offset.")),
            ("all", bool, typer.Option(False, "--all", help="Fetch every page.")),
        ]
    if operation.download:
        extras.append(("output", Path, typer.Option(..., "--output", "-o", help="Destination file ('-' for stdout).")))
    if operation.destructive:
        extras.append(("yes", bool, typer.Option(False, "--yes", "-y", help="Do not ask for confirmation.")))
    for name, python_type, default in extras:
        parameters.append(
            inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=python_type)
        )
        annotations[name] = python_type

    handler.__signature__ = inspect.Signature(parameters)
    handler.__annotations__ = annotations
    handler.__name__ = operation.id
    handler.__doc__ = operation.summary
    return handler


def _write_download(response, output):
    if str(output) == "-":
        sys.stdout.buffer.write(response.content)
        sys.stdout.buffer.flush()
        return
    Path(output).write_bytes(response.content)
    typer.echo(f"Saved {len(response.content)} bytes to {output}", err=True)


def build():
    for operation in OPERATIONS:
        _group_app(operation.group).command(name=operation.command, help=operation.summary)(_make_handler(operation))


build()


def main():
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
