from django.core.management.base import BaseCommand, CommandError

from parsifal.apps.core import backups
from parsifal.apps.core.exceptions import DomainError


class Command(BaseCommand):
    help = (
        "Restore the instance from a backup (.tar.gz: the database and the files; an old .sqlite3: the database). "
        "A backup of the current state is taken first. Stop other processes using the database first."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Backup file to restore.")
        parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation.")

    def handle(self, *args, **options):
        if not options["yes"]:
            answer = input(f"Replace the current database and files with {options['file']}? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                self.stdout.write("Aborted.")
                return
        try:
            safety, files = backups.restore_backup(options["file"])
        except DomainError as error:
            raise CommandError(str(error))
        self.stdout.write(f"The state before it was backed up to {safety}.")
        self.stdout.write(self.style.SUCCESS(f"Restored from {options['file']} ({files} files written)."))
