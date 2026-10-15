import sqlite3
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from parsifal.apps.core.management.commands.backup import open_database


def restore_sqlite(source):
    """Replace the live database contents with ``source`` (a file produced by `manage.py backup`)."""
    source = Path(source)
    if not source.exists():
        raise CommandError(f"{source} does not exist.")
    origin = sqlite3.connect(str(source))
    try:
        origin.execute("PRAGMA schema_version")  # fails early on a file that is not a SQLite database
    except sqlite3.DatabaseError:
        origin.close()
        raise CommandError(f"{source} is not a SQLite database.")
    target = open_database()
    try:
        origin.backup(target)
    finally:
        target.close()
        origin.close()


class Command(BaseCommand):
    help = "Restore the SQLite database from a backup file. Stop other processes using the database first."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Backup file to restore.")
        parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation.")

    def handle(self, *args, **options):
        if not options["yes"]:
            answer = input(f"Replace the current database with {options['file']}? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                self.stdout.write("Aborted.")
                return
        restore_sqlite(options["file"])
        self.stdout.write(self.style.SUCCESS(f"Database restored from {options['file']}."))
