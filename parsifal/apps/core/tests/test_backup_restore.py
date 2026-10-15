import io
import sqlite3
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TransactionTestCase, override_settings

from parsifal.apps.reviews.models import Source
from parsifal.apps.reviews.tests.factories import SourceFactory


class TestBackupAndRestore(TransactionTestCase):
    # TransactionTestCase: the backup API needs the data committed, not held in a test transaction.
    def setUp(self):
        if connection.vendor != "sqlite":
            self.skipTest("SQLite-only commands")
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def test_backup_default_location_and_restore(self):
        SourceFactory(name="Before backup")
        with override_settings(PARSIFAL_DATA_DIR=Path(self.folder.name)):
            out = io.StringIO()
            call_command("backup", stdout=out)
        backups = list((Path(self.folder.name) / "backups").glob("parsifal-*.sqlite3"))
        self.assertEqual(1, len(backups))
        self.assertIn("Backup written to", out.getvalue())

        with self.subTest(msg="backup is a readable sqlite database with the data"):
            copy = sqlite3.connect(str(backups[0]))
            names = [row[0] for row in copy.execute("SELECT name FROM reviews_source")]
            copy.close()
            self.assertIn("Before backup", names)

        Source.objects.filter(name="Before backup").delete()
        SourceFactory(name="After backup")
        call_command("restore", file=str(backups[0]), yes=True, stdout=io.StringIO())
        with self.subTest(msg="restore replaces the live database"):
            self.assertTrue(Source.objects.filter(name="Before backup").exists())
            self.assertFalse(Source.objects.filter(name="After backup").exists())

    def test_backup_explicit_output(self):
        target = Path(self.folder.name) / "nested" / "copy.sqlite3"
        call_command("backup", output=str(target), stdout=io.StringIO())
        self.assertTrue(target.exists())

    def test_restore_rejects_missing_or_invalid_files(self):
        with self.assertRaises(CommandError):
            call_command("restore", file=str(Path(self.folder.name) / "missing.sqlite3"), yes=True)
        bogus = Path(self.folder.name) / "bogus.sqlite3"
        bogus.write_text("not a database")
        with self.assertRaises(CommandError):
            call_command("restore", file=str(bogus), yes=True)
