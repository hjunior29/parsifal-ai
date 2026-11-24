from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.tests.files import PDF, TemporaryFilesMixin
from parsifal.apps.reviews.services import manuscripts
from parsifal.apps.reviews.tests.factories import ReviewFactory


class ManuscriptsViewTest(TemporaryFilesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserFactory(username="owner")
        cls.colleague = UserFactory(username="colleague")
        cls.review = ReviewFactory(author=cls.owner, co_authors=[cls.colleague])
        cls.url = reverse("manuscripts", args=(cls.owner.username, cls.review.name))

    def setUp(self):
        super().setUp()
        self.client.force_login(self.colleague)

    def file_url(self, version):
        return reverse("reviews:reporting:manuscript_file", args=(version.pk,))

    def test_members_only(self):
        paper = manuscripts.add_manuscript(review=self.review, name="Full paper")
        version = manuscripts.add_version(
            review=self.review, manuscript_id=paper.pk, file=SimpleUploadedFile("paper.pdf", PDF)
        )
        self.client.force_login(UserFactory())
        self.assertEqual(404, self.client.get(self.url).status_code)
        self.assertEqual(404, self.client.get(self.file_url(version)).status_code)
        self.client.logout()
        self.assertEqual(302, self.client.get(self.file_url(version)).status_code)  # to the login

    def test_add_upload_read_and_delete(self):
        response = self.client.post(
            self.url, {"action": "add", "name": "Extended abstract", "description": "4 pages"}, follow=True
        )
        self.assertContains(response, "The manuscript was added.")
        self.assertContains(response, "No version yet: upload the first one.")
        paper = self.review.manuscripts.get()
        response = self.client.post(
            self.url,
            {
                "action": "upload",
                "manuscript-id": paper.pk,
                "file": SimpleUploadedFile("abstract.pdf", PDF),
                "notes": "Sent to the venue",
            },
            follow=True,
        )
        self.assertContains(response, "Version 1 was uploaded.")
        version = paper.versions.get()
        self.assertContains(response, "abstract.pdf")
        self.assertContains(response, "Sent to the venue")
        self.assertContains(response, f'data-src="{self.file_url(version)}"', html=False)  # read here

        shown = self.client.get(self.file_url(version))
        self.assertEqual(
            ("inline", "SAMEORIGIN"), (shown["Content-Disposition"].split(";")[0], shown["X-Frame-Options"])
        )
        self.assertEqual(PDF, b"".join(shown.streaming_content))
        saved = self.client.get(self.file_url(version), {"download": ""})
        self.assertTrue(saved["Content-Disposition"].startswith("attachment"))

        response = self.client.post(
            self.url,
            {"action": "upload", "manuscript-id": paper.pk, "file": SimpleUploadedFile("abstract.pdf", b"no")},
            follow=True,
        )
        self.assertContains(response, "The file is not a PDF, as its name says.")
        self.client.post(self.url, {"action": "update", "manuscript-id": paper.pk, "name": "Short paper"})
        paper.refresh_from_db()
        self.assertEqual(("Short paper", ""), (paper.name, paper.description))
        self.client.post(self.url, {"action": "remove-version", "version-id": version.pk})
        self.assertFalse(paper.versions.exists())
        self.client.post(self.url, {"action": "remove", "manuscript-id": paper.pk})
        self.assertFalse(self.review.manuscripts.exists())

    def test_not_a_pdf_is_downloaded(self):
        paper = manuscripts.add_manuscript(review=self.review, name="Full paper")
        version = manuscripts.add_version(
            review=self.review, manuscript_id=paper.pk, file=SimpleUploadedFile("main.tex", b"\\section{Intro}")
        )
        response = self.client.get(self.url)
        self.assertNotContains(response, "glyphicon-eye-open")  # no Read button
        self.assertTrue(self.client.get(self.file_url(version))["Content-Disposition"].startswith("attachment"))
