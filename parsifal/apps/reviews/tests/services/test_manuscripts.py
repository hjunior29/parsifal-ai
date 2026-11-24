import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.exceptions import NotFound, ValidationError
from parsifal.apps.core.models import StoredFile
from parsifal.apps.core.tests.files import PDF, TemporaryFilesMixin
from parsifal.apps.reviews.models import ManuscriptVersion, ReviewEvent
from parsifal.apps.reviews.services import manuscripts
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory


def docx():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


class ManuscriptsTestCase(TemporaryFilesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = UserFactory(username="alice")
        cls.review = ReviewFactory(author=cls.author)

    def add(self, name="Full paper", **kwargs):
        return manuscripts.add_manuscript(review=self.review, name=name, actor=self.author, **kwargs)

    def upload(self, manuscript, content=PDF, name="paper.pdf", **kwargs):
        return manuscripts.add_version(
            review=self.review,
            manuscript_id=manuscript.pk,
            file=SimpleUploadedFile(name, content),
            actor=self.author,
            **kwargs,
        )


class TestManuscripts(ManuscriptsTestCase):
    def test_any_name_once_per_review(self):
        paper = self.add("  Paper in the SBC template  ", description="12 pages")
        self.assertEqual(
            ("Paper in the SBC template", "12 pages", self.author), (paper.name, paper.description, paper.created_by)
        )
        with self.assertRaises(ValidationError):
            self.add("paper in the sbc TEMPLATE")
        with self.assertRaises(ValidationError):
            self.add("  ")
        other = self.add("Extended abstract")
        with self.assertRaises(ValidationError):
            manuscripts.update_manuscript(review=self.review, manuscript_id=other.pk, name="Paper in the SBC template")
        renamed = manuscripts.update_manuscript(review=self.review, manuscript_id=other.pk, name="Short paper")
        self.assertEqual(("Short paper", ""), (renamed.name, renamed.description))
        self.assertEqual(
            ["Paper in the SBC template", "Short paper"], [m.name for m in manuscripts.list_manuscripts(self.review)]
        )
        with self.assertRaises(NotFound):
            manuscripts.update_manuscript(review=ReviewFactory(), manuscript_id=other.pk, name="Mine")

    def test_each_upload_is_a_new_version(self):
        paper = self.add()
        first = self.upload(paper, name="draft.pdf")
        second = self.upload(paper, content=docx(), name="C:\\Users\\me\\paper v2.docx", notes="Reviewers' comments")
        self.assertEqual((1, 2), (first.number, second.number))
        self.assertEqual(
            ("draft.pdf", "application/pdf", True), (first.file.filename, first.file.content_type, first.is_pdf)
        )
        self.assertEqual(
            ("paper v2.docx", manuscripts.FORMATS["docx"][0], False, "Reviewers' comments"),
            (second.file.filename, second.file.content_type, second.is_pdf, second.notes),
        )
        self.assertTrue(second.file.key.startswith(f"reviews/{self.review.pk}/manuscripts/"))
        with second.file.open() as handle:
            self.assertEqual(docx(), handle.read())
        self.assertEqual([2, 1], [v.number for v in paper.versions.all()])
        tex = self.upload(paper, content=b"\\documentclass{article}\n", name="main.tex")
        self.assertEqual((3, "application/x-tex"), (tex.number, tex.file.content_type))

    def test_the_content_must_be_what_the_name_says(self):
        paper = self.add()
        for content, name in (
            (b"not a pdf", "paper.pdf"),
            (PDF, "paper.docx"),
            (b"\x00\x01binary", "main.tex"),
            (PDF, "paper.exe"),
            (b"", "paper.pdf"),
            (PDF, "no-extension"),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    self.upload(paper, content=content, name=name)
        self.assertFalse(paper.versions.exists())
        with override_settings(PARSIFAL_PDF_MAX_MB=0):
            with self.assertRaises(ValidationError):
                self.upload(paper)

    def test_removing_a_version_or_the_manuscript_removes_the_files(self):
        paper = self.add()
        first, second = self.upload(paper), self.upload(paper)
        manuscripts.remove_version(review=self.review, version_id=first.pk)
        self.assertEqual([2], [v.number for v in paper.versions.all()])
        self.assertFalse(StoredFile.objects.filter(pk=first.file_id).exists())
        with self.assertRaises(NotFound):
            manuscripts.remove_version(review=ReviewFactory(), version_id=second.pk)
        manuscripts.remove_manuscript(review=self.review, manuscript_id=paper.pk)
        self.assertFalse(ManuscriptVersion.objects.exists())
        self.assertFalse(StoredFile.objects.filter(pk=second.file_id).exists())

    def test_history_in_reporting(self):
        ArticleFactory(review=self.review)  # not an amendment, studies or not
        paper = self.add(description="SBES")
        version = self.upload(paper, notes="First draft")
        manuscripts.update_manuscript(review=self.review, manuscript_id=paper.pk, description="SBES 2026")
        manuscripts.remove_version(review=self.review, version_id=version.pk)
        self.upload(paper, name="final.pdf")
        manuscripts.remove_manuscript(review=self.review, manuscript_id=paper.pk)
        events = list(self.review.events.order_by("pk"))
        self.assertEqual(
            [
                "Added the manuscript “Full paper”",
                "Uploaded version 1 of the manuscript “Full paper”",
                "Changed the manuscript “Full paper”",
                "Removed version 1 of the manuscript “Full paper”",
                "Uploaded version 2 of the manuscript “Full paper”",  # 1 is not given twice
                "Removed the manuscript “Full paper” and its 1 version",
            ],
            [event.summary for event in events],
        )
        self.assertEqual({ReviewEvent.REPORTING}, {event.area for event in events})
        self.assertEqual({False}, {event.amendment for event in events})
        self.assertEqual(["paper.pdf"], events[1].items)
        self.assertEqual([{"key": "notes", "field": "Notes", "before": "", "after": "First draft"}], events[1].changes)
        self.assertEqual(["v2: final.pdf"], events[-1].items)
        self.assertEqual(self.author, events[1].actor)
