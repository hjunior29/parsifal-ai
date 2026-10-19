import hashlib
import io
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.exceptions import NotFound, ValidationError
from parsifal.apps.core.models import StoredFile
from parsifal.apps.core.tests.files import PDF, TemporaryFilesMixin
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.services import full_texts, studies
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory, SourceFactory


class TestFullTexts(TemporaryFilesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.author = UserFactory(username="alice")
        cls.reviewer = UserFactory(username="bob")
        cls.review = ReviewFactory(author=cls.author, co_authors=[cls.reviewer], sources=[cls.source])
        cls.article = ArticleFactory(review=cls.review, source=cls.source, status=Article.REJECTED)
        Article.objects.filter(pk=cls.article.pk).update(updated_by=cls.reviewer)

    def attach(self, content=PDF, name="paper.pdf", article=None, **kwargs):
        return full_texts.attach_pdf(
            review=self.review,
            article_id=(article or self.article).pk,
            file=SimpleUploadedFile(name, content, content_type="application/pdf"),
            actor=self.author,
            **kwargs,
        )

    def test_attach_keeps_the_file_and_leaves_the_status_alone(self):
        before = Article.objects.get(pk=self.article.pk)
        pdf = self.attach()
        article = Article.objects.select_related("pdf").get(pk=self.article.pk)
        self.assertEqual(pdf, article.pdf)
        self.assertEqual(
            ("paper.pdf", "application/pdf", len(PDF), hashlib.sha256(PDF).hexdigest(), self.author),
            (pdf.filename, pdf.content_type, pdf.size, pdf.sha256, pdf.uploaded_by),
        )
        self.assertTrue(pdf.key.startswith(f"reviews/{self.review.pk}/") and pdf.key.endswith(".pdf"))
        self.assertEqual([pdf.key], self.stored_files())
        with pdf.open() as stored:
            self.assertEqual(PDF, stored.read())
        with self.subTest(msg="any status, and who set it, is untouched (AI screening relies on updated_by)"):
            self.assertEqual(
                (Article.REJECTED, self.reviewer.pk, before.updated_at),
                (article.status, article.updated_by_id, article.updated_at),
            )

    def test_any_binary_file_object(self):
        pdf = full_texts.attach_pdf(review=self.review, article_id=self.article.pk, file=io.BytesIO(PDF))
        self.assertEqual((f"article-{self.article.pk}.pdf", None), (pdf.filename, pdf.uploaded_by))
        with self.subTest(msg="a few bytes before the header are accepted, like PDF readers do"):
            pdf = self.attach(b"\xef\xbb\xbf\n" + PDF)
            self.assertEqual(len(PDF) + 4, pdf.size)

    def test_filename(self):
        cases = {
            "C:\\Users\\me\\Downloads\\Smith 2020.PDF": "Smith 2020.pdf",
            "../../etc/passwd": "passwd.pdf",
            "line\nbreak.pdf": "linebreak.pdf",
            ".pdf": f"article-{self.article.pk}.pdf",
            "x" * 300 + ".pdf": "x" * 200 + ".pdf",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(expected, self.attach(name=name).filename)

    def test_refuses_what_is_not_a_pdf_and_stores_nothing(self):
        cases = {
            "not a PDF": (b"<html><body>paper.pdf</body></html>", "Only PDF files are accepted."),
            "PDF header too far in": (b" " * 1024 + PDF, "Only PDF files are accepted."),
            "empty": (b"", "The file is empty."),
        }
        for label, (content, message) in cases.items():
            with self.subTest(label), self.assertRaisesMessage(ValidationError, message):
                self.attach(content)
        with self.subTest("too big"), override_settings(PARSIFAL_PDF_MAX_MB=1):
            with self.assertRaisesMessage(ValidationError, "The PDF must be at most 1 MB."):
                self.attach(PDF + b"0" * 1024 * 1024)
            with self.assertRaisesMessage(ValidationError, "The PDF must be at most 1 MB."):
                full_texts.attach_pdf(
                    review=self.review, article_id=self.article.pk, file=io.BytesIO(PDF + b"0" * 1024 * 1024)
                )
        self.assertEqual([], self.stored_files())
        self.assertFalse(StoredFile.objects.exists())

    def test_a_failure_after_storing_removes_the_object(self):
        with mock.patch.object(StoredFile.objects, "create", side_effect=RuntimeError("database is locked")):
            with self.assertRaises(RuntimeError):
                self.attach()
        self.assertEqual([], self.stored_files())

    def test_replace_deletes_the_previous_file(self):
        first = self.attach(name="v1.pdf")
        with self.captureOnCommitCallbacks(execute=True):
            second = self.attach(PDF + b"% v2\n", name="v2.pdf")
        self.assertEqual([second.key], self.stored_files())
        self.assertEqual(["v2.pdf"], list(StoredFile.objects.values_list("filename", flat=True)))
        self.assertNotEqual(first.key, second.key)

    def test_remove(self):
        with self.assertRaisesMessage(NotFound, f"Article {self.article.pk} has no PDF."):
            full_texts.remove_pdf(review=self.review, article_id=self.article.pk)
        self.attach()
        with self.captureOnCommitCallbacks(execute=True):
            full_texts.remove_pdf(review=self.review, article_id=self.article.pk)
        self.assertIsNone(Article.objects.get(pk=self.article.pk).pdf)
        self.assertEqual([], self.stored_files())
        with self.assertRaises(NotFound):
            full_texts.get_pdf(review=self.review, article_id=self.article.pk)

    def test_the_file_goes_with_its_study(self):
        others = ArticleFactory.create_batch(2, review=self.review, source=self.source)
        for article in (self.article, *others):
            self.attach(article=article)
        with self.captureOnCommitCallbacks(execute=True):
            studies.delete_articles(review=self.review, article_ids=[self.article.pk])
        self.assertEqual(2, len(self.stored_files()))
        with self.captureOnCommitCallbacks(execute=True):
            studies.clear_articles(review=self.review, source_id=self.source.pk)
        self.assertEqual([], self.stored_files())
        self.assertFalse(StoredFile.objects.exists())

        with self.subTest(msg="deleting the review"):
            review = ReviewFactory(author=self.author, sources=[self.source])
            article = ArticleFactory(review=review, source=self.source)
            full_texts.attach_pdf(review=review, article_id=article.pk, file=io.BytesIO(PDF))
            with self.captureOnCommitCallbacks(execute=True):
                review.delete()
            self.assertEqual([], self.stored_files())

    def test_scoped_to_the_review(self):
        other = ArticleFactory(review=ReviewFactory(), source=self.source)
        with self.assertRaises(NotFound):
            self.attach(article=other)
        with self.assertRaises(NotFound):
            full_texts.get_pdf(review=self.review, article_id=other.pk)
        self.assertEqual([], self.stored_files())
