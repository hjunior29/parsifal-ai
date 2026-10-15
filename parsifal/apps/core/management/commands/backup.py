import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def open_database():
    """A dedicated sqlite3 connection to the configured database (file path or shared-cache memory URI)."""
    if connection.vendor != "sqlite":
        raise CommandError("Backups are only implemented for SQLite.")
    connection.ensure_connection()  # keeps shared-cache in-memory databases (tests) alive
    name = str(connection.settings_dict["NAME"])
    return sqlite3.connect(name, uri=name.startswith("file:"))


def backup_sqlite(destination):
    """
    Consistent copy of the live SQLite database using the online backup API. A separate read connection is
    used so the copy works while the application is running (WAL mode) and never touches Django's connection.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = open_database()
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return destination


class Command(BaseCommand):
    help = "Back up the SQLite database to PARSIFAL_DATA_DIR/backups/ (or --output)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output", help="Destination file. Default: <data dir>/backups/parsifal-<timestamp>.sqlite3"
        )

    def handle(self, *args, **options):
        if options["output"]:
            destination = Path(options["output"])
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            destination = Path(settings.PARSIFAL_DATA_DIR) / "backups" / f"parsifal-{stamp}.sqlite3"
        backup_sqlite(destination)
        self.stdout.write(f"Backup written to {destination} ({destination.stat().st_size} bytes).")
