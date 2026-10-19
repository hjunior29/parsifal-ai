"""Helpers for tests that upload files."""

import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import override_settings

# The smallest file the PDF check accepts is enough: nothing renders it in the tests.
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


class TemporaryFilesMixin:
    """Keeps the "files" storage in a folder of the test class's own, removed when the class is done."""

    @classmethod
    def setUpClass(cls):
        cls.files_dir = Path(tempfile.mkdtemp(prefix="parsifal-test-files-"))
        storages = dict(settings.STORAGES)
        storages["files"] = {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(cls.files_dir)},
        }
        cls._files_override = override_settings(STORAGES=storages)
        cls._files_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._files_override.disable()
        shutil.rmtree(cls.files_dir, ignore_errors=True)

    def setUp(self):
        super().setUp()
        # The database is rolled back after each test, the folder is not.
        for path in self.files_dir.iterdir():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    def stored_files(self):
        """Paths (relative to the storage) of every stored file."""
        return sorted(str(path.relative_to(self.files_dir)) for path in self.files_dir.rglob("*") if path.is_file())
