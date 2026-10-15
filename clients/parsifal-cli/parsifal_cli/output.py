"""Rendering: JSON when piped (or --json), compact tables for humans on a terminal."""

import sys

from rich.console import Console
from rich.table import Table

from parsifal_cli.client import dumps

console = Console()
error_console = Console(stderr=True)

TABLE_MAX_CELL = 60


def want_json(force_json):
    return force_json or not sys.stdout.isatty()


def render(data, force_json=False):
    if want_json(force_json):
        if data is None:
            return
        console.print_json(dumps(data)) if sys.stdout.isatty() else print(dumps(data))
        return
    if data is None:
        console.print("[green]OK[/green]")
    elif isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        _table(data["items"])
        console.print(f"[dim]{len(data['items'])} of {data.get('count', len(data['items']))}[/dim]")
    elif isinstance(data, list):
        _table(data)
    elif isinstance(data, dict):
        _key_values(data)
    else:
        console.print(str(data))


def _cell(value):
    if isinstance(value, (dict, list)):
        value = dumps(value).replace("\n", " ")
    text = "" if value is None else str(value)
    return text if len(text) <= TABLE_MAX_CELL else text[: TABLE_MAX_CELL - 1] + "…"


def _table(rows):
    if not rows:
        console.print("[dim](empty)[/dim]")
        return
    if not all(isinstance(row, dict) for row in rows):
        for row in rows:
            console.print(_cell(row))
        return
    columns = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    table = Table(show_lines=False, header_style="bold")
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*[_cell(row.get(column)) for column in columns])
    console.print(table)


def _key_values(data):
    table = Table(show_header=False, box=None)
    table.add_column(style="bold")
    table.add_column()
    for key, value in data.items():
        table.add_row(key, _cell(value) if not isinstance(value, (dict, list)) else dumps(value))
    console.print(table)


def error(message):
    error_console.print(f"[red]error:[/red] {message}")
