from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.tests.files import TemporaryFilesMixin
from parsifal.apps.reviews.models import Article, Review
from parsifal.apps.reviews.services import review_backups
from parsifal.apps.reviews.tests.factories import ReviewFactory, SourceFactory


class TestReviewBackupsView(TemporaryFilesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = UserFactory()
        cls.co_author = UserFactory()
        cls.source = SourceFactory()
        cls.review = ReviewFactory(author=cls.author, co_authors=[cls.co_author], sources=[cls.source])
        Article.objects.create(review=cls.review, source=cls.source, title="One", status="A")
        cls.url = reverse("review_backups", args=(cls.author.username, cls.review.name))

    def setUp(self):
        super().setUp()
        self.client.force_login(self.author)

    def post(self, **data):
        return self.client.post(self.url, data, follow=True)

    def test_back_up_download_restore_delete(self):
        response = self.client.get(self.url)
        self.assertContains(response, "No backups yet.")
        self.assertContains(response, 'class="list-group-item active">Backups</a>', html=False)
        response = self.post(action="create")
        self.assertContains(response, "The review was backed up.")
        backup = self.review.backups.get()
        self.assertContains(response, backup.file.filename)
        download = self.client.get(
            reverse("download_review_backup", args=(self.author.username, self.review.name, backup.pk))
        )
        content = b"".join(download.streaming_content)
        self.assertIn(f'filename="{backup.file.filename}"', download["Content-Disposition"])
        upload = SimpleUploadedFile("mine.tar.gz", content, content_type="application/gzip")
        self.assertContains(self.post(action="upload", file=upload), "The backup file was added to the list.")
        bogus = SimpleUploadedFile("bogus.tar.gz", b"nope", content_type="application/gzip")
        self.assertContains(self.post(action="upload", file=bogus), "The file is not a backup of a review.")
        Article.objects.filter(review=self.review).delete()
        response = self.post(action="restore", backup_id=backup.pk)
        self.assertContains(response, "The review was restored.")
        self.assertEqual(["One"], list(self.review.article_set.values_list("title", flat=True)))
        self.assertContains(self.post(action="delete", backup_id=backup.pk), "The backup was deleted.")
        self.assertEqual(2, self.review.backups.count())

    def test_only_the_main_author(self):
        self.client.force_login(self.co_author)
        self.assertEqual(403, self.client.get(self.url).status_code)


class TestImportReviewView(TemporaryFilesMixin, TestCase):
    def test_a_new_review_from_a_backup(self):
        author = UserFactory()
        review = ReviewFactory(author=author, title="Agents")
        backup = review_backups.create_backup(review=review, actor=author)
        with backup.file.open() as handle:
            content = handle.read()
        newcomer = UserFactory()
        self.client.force_login(newcomer)
        self.assertContains(self.client.get(reverse("reviews:new")), "Or import a review backup")
        file = SimpleUploadedFile("agents.tar.gz", content, content_type="application/gzip")
        response = self.client.post(reverse("reviews:import_review"), {"file": file}, follow=True)
        copy = Review.objects.get(author=newcomer)
        self.assertRedirects(response, reverse("review", args=(newcomer.username, copy.name)))
        self.assertContains(response, "The review was imported from the backup.")
        bogus = SimpleUploadedFile("bogus.tar.gz", b"nope", content_type="application/gzip")
        response = self.client.post(reverse("reviews:import_review"), {"file": bogus}, follow=True)
        self.assertContains(response, "The file is not a backup of a review.")
        self.assertEqual(405, self.client.get(reverse("reviews:import_review")).status_code)
