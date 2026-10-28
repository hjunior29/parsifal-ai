from django.core.management.base import BaseCommand, CommandError

from parsifal.apps.core import backups
from parsifal.apps.core.exceptions import DomainError


class Command(BaseCommand):
    help = (
        "Back up the instance to one .tar.gz: the SQLite database, the studies' PDFs (from the data directory or the "
        "bucket) and a manifest. Default: <data dir>/backups/parsifal-<timestamp>.tar.gz."
    )

    def add_arguments(self, parser):
        parser.add_argument("--output", help="Destination file (.tar.gz).")
        parser.add_argument(
            "--keep",
            type=int,
            help="Then keep only the newest KEEP timestamped backups (parsifal-<timestamp>.tar.gz) of that folder.",
        )

    def handle(self, *args, **options):
        try:
            destination, files = backups.create_backup(options["output"], keep=options["keep"])
        except DomainError as error:
            raise CommandError(str(error))
        self.stdout.write(
            f"Backup written to {destination} ({destination.stat().st_size} bytes, the database and {files} files)."
        )
