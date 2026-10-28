import io
import tarfile

from django.core.files.uploadedfile import SimpleUploadedFile

from parsifal.api.tests.base import API, ApiTestCase
from parsifal.apps.core.tests.files import TemporaryFilesMixin
from parsifal.apps.reviews.models import Article, Review


class TestReviewBackupsApi(TemporaryFilesMixin, ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Article.objects.create(review=cls.review, source=cls.source, title="One", status="A")

    def upload(self, path, content, client=None):
        file = SimpleUploadedFile("backup.tar.gz", content, content_type="application/gzip")
        return (client or self.client).post(f"{API}{path}", {"file": file})

    def test_create_list_download_upload_restore_delete(self):
        created = self.api("post", self.review_path("/backups"))
        self.assertEqual(201, created.status_code, created.content)
        backup = created.json()
        self.assertEqual((1, ""), (backup["studies"], backup["note"]))
        self.assertEqual([backup["id"]], [row["id"] for row in self.api("get", self.review_path("/backups")).json()])
        download = self.api("get", self.review_path(f"/backups/{backup['id']}/download"))
        content = b"".join(download.streaming_content)
        self.assertIn("review.json", tarfile.open(fileobj=io.BytesIO(content)).getnames())
        uploaded = self.upload(self.review_path("/backups/upload"), content)
        self.assertEqual((201, "Uploaded"), (uploaded.status_code, uploaded.json()["note"]))
        self.assertEqual(422, self.upload(self.review_path("/backups/upload"), b"nope").status_code)
        Article.objects.filter(review=self.review).delete()
        restored = self.api("post", self.review_path(f"/backups/{backup['id']}/restore"))
        self.assertEqual((200, self.review.pk), (restored.status_code, restored.json()["id"]))
        self.assertEqual(["One"], list(self.review.article_set.values_list("title", flat=True)))
        self.assertEqual(3, len(self.api("get", self.review_path("/backups")).json()))  # + the one before restoring
        self.assertEqual(204, self.api("delete", self.review_path(f"/backups/{backup['id']}")).status_code)
        self.assertEqual(404, self.api("delete", self.review_path(f"/backups/{backup['id']}")).status_code)

    def test_import_a_new_review(self):
        backup = self.api("post", self.review_path("/backups")).json()
        content = b"".join(self.api("get", self.review_path(f"/backups/{backup['id']}/download")).streaming_content)
        response = self.upload("/reviews/import", content, client=self.client_for(self.outsider))
        self.assertEqual(201, response.status_code, response.content)
        copy = Review.objects.get(pk=response.json()["id"])
        self.assertEqual(
            (self.outsider, ["One"]), (copy.author, list(copy.article_set.values_list("title", flat=True)))
        )
        self.assertEqual(422, self.upload("/reviews/import", b"nope").status_code)

    def test_only_the_main_author(self):
        self.assertEqual(
            403, self.api("post", self.review_path("/backups"), client=self.client_for(self.co_author)).status_code
        )
        self.assertEqual(
            404, self.api("get", self.review_path("/backups"), client=self.client_for(self.outsider)).status_code
        )
