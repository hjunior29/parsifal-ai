import importlib
import os
from unittest import mock

from django.test import SimpleTestCase


def load_base(**env):
    """Import the base settings with a controlled environment (python-decouple reads os.environ)."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("PARSIFAL_FILES", "AWS_"))}
    clean.update(env)
    with mock.patch.dict(os.environ, clean, clear=True):
        import parsifal.settings.base as base

        return importlib.reload(base)


class TestFilesStorageSettings(SimpleTestCase):
    def tearDown(self):
        load_base()  # leave the module as the environment configures it

    def test_a_private_folder_in_the_data_directory_by_default(self):
        settings = load_base()
        files = settings.STORAGES["files"]
        self.assertEqual("django.core.files.storage.FileSystemStorage", files["BACKEND"])
        self.assertEqual(str(settings.PARSIFAL_DATA_DIR / "files"), files["OPTIONS"]["location"])
        self.assertNotEqual(str(settings.MEDIA_ROOT), files["OPTIONS"]["location"])
        self.assertEqual(50, settings.PARSIFAL_PDF_MAX_MB)

    def test_a_bucket_when_one_is_named(self):
        settings = load_base(
            PARSIFAL_FILES_BUCKET="my-papers",
            AWS_ENDPOINT_URL_S3="https://fly.storage.tigris.dev",
            AWS_REGION="auto",
            AWS_ACCESS_KEY_ID="tid_not_a_real_key",
            AWS_SECRET_ACCESS_KEY="tsec_not_a_real_secret",
        )
        files = settings.STORAGES["files"]
        self.assertEqual("storages.backends.s3.S3Storage", files["BACKEND"])
        self.assertEqual(
            {
                "bucket_name": "my-papers",
                "endpoint_url": "https://fly.storage.tigris.dev",
                "region_name": "auto",
                "location": "",
                "default_acl": None,
                "querystring_auth": True,
                "querystring_expire": 300,
                "signature_version": "s3v4",
                "file_overwrite": False,
            },
            files["OPTIONS"],
        )
        # boto3 reads the credentials from the environment; they never enter the settings.
        values = repr([getattr(settings, name) for name in dir(settings)])
        self.assertNotIn("tsec_not_a_real_secret", values)
        self.assertNotIn("tid_not_a_real_key", values)
