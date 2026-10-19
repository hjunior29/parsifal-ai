"""
The studies' full texts: one PDF per study, whatever its status, kept in the "files" storage (a private folder in the
data directory, or an S3-compatible bucket when PARSIFAL_FILES_BUCKET is set). ``Article.pdf`` points at the
StoredFile row; replacing or removing the PDF, or deleting the study, deletes the stored object too.
"""

import hashlib
import re
import uuid

from django.conf import settings
from django.core.files import File
from django.db import transaction

from parsifal.apps.core.exceptions import NotFound, ValidationError
from parsifal.apps.core.models import StoredFile, files_storage
from parsifal.apps.reviews.services._common import get_child

PDF_CONTENT_TYPE = "application/pdf"
PDF_SIGNATURE = b"%PDF-"
SIGNATURE_WINDOW = 1024  # readers accept a few bytes of junk before the header, so look a little further


def max_size_mb():
    return settings.PARSIFAL_PDF_MAX_MB


def _article(review, article_id):
    return get_child(review.article_set.select_related("pdf"), article_id, label="Article")


def get_pdf(*, review, article_id):
    """The study's PDF (a StoredFile); NotFound when it has none."""
    article = _article(review, article_id)
    if article.pdf is None:
        raise NotFound(f"Article {article.pk} has no PDF.")
    return article.pdf


def _clean_filename(name, article):
    name = re.split(r"[\\/]", str(name or ""))[-1]  # browsers on Windows may send the whole path
    name = "".join(char for char in name if char.isprintable()).strip()
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    return f"{stem[:200] or f'article-{article.pk}'}.pdf"


def _inspect(file):
    """Size and SHA-256 of a PDF, refusing anything else (judged by its first bytes, not its name) or too big."""
    limit = max_size_mb() * 1024 * 1024
    if file.size is not None and file.size > limit:
        raise ValidationError(f"The PDF must be at most {max_size_mb()} MB.", field="file")
    digest, size, head = hashlib.sha256(), 0, b""
    for chunk in file.chunks():
        size += len(chunk)
        if size > limit:
            raise ValidationError(f"The PDF must be at most {max_size_mb()} MB.", field="file")
        if len(head) < SIGNATURE_WINDOW:
            head += chunk[: SIGNATURE_WINDOW - len(head)]
        digest.update(chunk)
    if not size:
        raise ValidationError("The file is empty.", field="file")
    if PDF_SIGNATURE not in head:
        raise ValidationError("Only PDF files are accepted.", field="file")
    file.seek(0)
    return size, digest.hexdigest()


def attach_pdf(*, review, article_id, file, filename=None, actor=None):
    """
    Keep ``file`` (an upload or any binary file object) as the study's PDF, replacing the one it had. Up to
    PARSIFAL_PDF_MAX_MB. The study's status and who set it are left alone.
    """
    article = _article(review, article_id)
    if not isinstance(file, File):
        file = File(file)
    size, sha256 = _inspect(file)
    storage = files_storage()
    key = storage.save(f"reviews/{review.pk}/{uuid.uuid4().hex}.pdf", file)
    try:
        with transaction.atomic():
            previous = article.pdf
            article.pdf = StoredFile.objects.create(
                key=key,
                filename=_clean_filename(filename or file.name, article),
                content_type=PDF_CONTENT_TYPE,
                size=size,
                sha256=sha256,
                uploaded_by=actor,
            )
            article.save(update_fields=["pdf"])
            if previous is not None:
                previous.delete()  # its object goes once this commits
    except Exception:
        storage.delete(key)
        raise
    return article.pdf


def remove_pdf(*, review, article_id):
    """Delete the study's PDF; NotFound when it has none."""
    get_pdf(review=review, article_id=article_id).delete()
