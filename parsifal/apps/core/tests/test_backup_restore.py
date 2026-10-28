import io
import json
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TransactionTestCase, override_settings

from parsifal.apps.core import backups
from parsifal.apps.core.models import files_storage
from parsifal.apps.core.tests.files import PDF, TemporaryFilesMixin
from parsifal.apps.reviews.models import Source
from parsifal.apps.reviews.tests.factories import SourceFactory


class TestBackupAndRestore(TemporaryFilesMixin, TransactionTestCase):
    # TransactionTestCase: the backup API needs the data committed, not held in a test transaction.
    def setUp(self):
        if connection.vendor != "sqlite":
            self.skipTest("SQLite-only commands")
        super().setUp()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.data_dir = override_settings(PARSIFAL_DATA_DIR=Path(self.folder.name))
        self.data_dir.enable()
        self.addCleanup(self.data_dir.disable)

    def backup(self, **options):
        out = io.StringIO()
        call_command("backup", stdout=out, **options)
        return out.getvalue()

    def test_one_archive_with_the_database_the_files_and_a_manifest(self):
        SourceFactory(name="Before backup")
        files_storage().save("reviews/1/study.pdf", ContentFile(PDF))
        self.assertIn("the database and 1 files", self.backup())
        archives = list((Path(self.folder.name) / "backups").glob("parsifal-*.tar.gz"))
        self.assertEqual(1, len(archives))
        with tarfile.open(archives[0]) as archive:
            self.assertEqual(
                {"parsifal.sqlite3", "files/reviews/1/study.pdf", "manifest.json"}, set(archive.getnames())
            )
            manifest = json.loads(archive.extractfile("manifest.json").read())
            self.assertEqual(PDF, archive.extractfile("files/reviews/1/study.pdf").read())
            with tempfile.TemporaryDirectory() as scratch:
                archive.extract("parsifal.sqlite3", scratch)
                copy = sqlite3.connect(str(Path(scratch) / "parsifal.sqlite3"))
                names = [row[0] for row in copy.execute("SELECT name FROM reviews_source")]
                copy.close()
        self.assertIn("Before backup", names)
        self.assertEqual((1, "local"), (manifest["format"], manifest["files_storage"]))
        self.assertEqual(["reviews/1/study.pdf"], list(manifest["files"]))
        self.assertIn("reviews", manifest["migrations"])

    def test_restore_brings_back_the_database_and_the_missing_files(self):
        SourceFactory(name="Before backup")
        storage = files_storage()
        storage.save("reviews/1/study.pdf", ContentFile(PDF))
        self.backup()
        archive = next((Path(self.folder.name) / "backups").glob("parsifal-*.tar.gz"))
        Source.objects.filter(name="Before backup").delete()
        SourceFactory(name="After backup")
        storage.delete("reviews/1/study.pdf")
        out = io.StringIO()
        call_command("restore", file=str(archive), yes=True, stdout=out)
        self.assertTrue(Source.objects.filter(name="Before backup").exists())
        self.assertFalse(Source.objects.filter(name="After backup").exists())
        with storage.open("reviews/1/study.pdf") as handle:
            self.assertEqual(PDF, handle.read())
        self.assertIn("1 files written", out.getvalue())
        with self.subTest(msg="the state before the restore was backed up first"):
            safety = list((Path(self.folder.name) / "backups").glob("before-restore-*.tar.gz"))
            self.assertEqual(1, len(safety))
            self.assertIn(str(safety[0]), out.getvalue())

    def test_keep_only_the_newest(self):
        folder = Path(self.folder.name) / "backups"
        folder.mkdir()
        for stamp in ("20260101-000000", "20260102-000000", "20260103-000000"):
            (folder / f"parsifal-{stamp}.tar.gz").write_bytes(b"old")
        (folder / "parsifal-20261020-123448.sqlite3").write_bytes(b"older format, kept")
        self.backup(keep=2)
        names = sorted(path.name for path in folder.iterdir())
        self.assertEqual(3, len(names))
        self.assertIn("parsifal-20260103-000000.tar.gz", names)
        self.assertIn("parsifal-20261020-123448.sqlite3", names)
        self.assertNotIn("parsifal-20260101-000000.tar.gz", names)

    def test_backup_explicit_output(self):
        target = Path(self.folder.name) / "nested" / "copy.tar.gz"
        self.backup(output=str(target))
        self.assertTrue(tarfile.is_tarfile(target))

    def test_an_old_database_backup_still_restores(self):
        SourceFactory(name="Before backup")
        old = Path(self.folder.name) / "old.sqlite3"
        backups.backup_sqlite(old)
        Source.objects.filter(name="Before backup").delete()
        call_command("restore", file=str(old), yes=True, stdout=io.StringIO())
        self.assertTrue(Source.objects.filter(name="Before backup").exists())

    def test_restore_rejects_missing_invalid_or_damaged_files(self):
        with self.assertRaises(CommandError):
            call_command("restore", file=str(Path(self.folder.name) / "missing.tar.gz"), yes=True)
        bogus = Path(self.folder.name) / "bogus.sqlite3"
        bogus.write_text("not a database")
        with self.assertRaises(CommandError):
            call_command("restore", file=str(bogus), yes=True)
        not_tar = Path(self.folder.name) / "bogus.tar.gz"
        not_tar.write_text("not an archive")
        with self.assertRaisesMessage(CommandError, "is not a backup"):
            call_command("restore", file=str(not_tar), yes=True)
        files_storage().save("reviews/1/study.pdf", ContentFile(PDF))
        good = Path(self.folder.name) / "good.tar.gz"
        self.backup(output=str(good))
        damaged = Path(self.folder.name) / "damaged.tar.gz"
        with tarfile.open(good) as source, tarfile.open(damaged, "w:gz") as target:
            for member in source.getmembers():
                data = source.extractfile(member).read()
                if member.name.startswith("files/"):
                    data = data.replace(b"Catalog", b"Katalog")
                member.size = len(data)
                target.addfile(member, io.BytesIO(data))
        with self.assertRaisesMessage(CommandError, "The file reviews/1/study.pdf of the backup is damaged."):
            call_command("restore", file=str(damaged), yes=True)
