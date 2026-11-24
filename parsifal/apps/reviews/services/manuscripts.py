"""
The manuscripts written from a review — the paper, a short or an extended version of it, the same paper in another
template, a report for practitioners — each named as the review likes, with its versions: every file uploaded to a
manuscript is a new version, and none replaces another. A version's file is a PDF (read in the browser), a Word or
OpenDocument text, a LaTeX source or a ZIP (a LaTeX project), kept in the "files" storage like the studies' PDFs.
"""

import hashlib
import re
import uuid

from django.core.files import File
from django.db import transaction
from django.db.models import Max

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.core.models import StoredFile, files_storage
from parsifal.apps.reviews.models import Manuscript, ManuscriptVersion, ReviewEvent
from parsifal.apps.reviews.services import full_texts, history
from parsifal.apps.reviews.services._common import check_length, get_child, require

# The files a version may have: extension → (content type, what it is). The content must match the extension.
FORMATS = {
    "pdf": ("application/pdf", "PDF"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Word document"),
    "odt": ("application/vnd.oasis.opendocument.text", "OpenDocument text"),
    "tex": ("application/x-tex", "LaTeX source"),
    "zip": ("application/zip", "ZIP archive (a LaTeX project, for instance)"),
}
ZIP_SIGNATURE = b"PK\x03\x04"  # .docx and .odt are ZIP archives too

# Names suggested for a manuscript; any other is accepted.
SUGGESTED_NAMES = (
    "Full paper",
    "Short paper",
    "Extended abstract",
    "Journal article",
    "Technical report",
    "Thesis chapter",
    "Poster",
    "Slides",
)

# What the History records of the manuscripts.
MANUSCRIPT = history.Kind("manuscript", ReviewEvent.REPORTING, ("name", "description"))


def max_size_mb():
    return full_texts.max_size_mb()


def accepted_extensions():
    """ ".pdf,.docx,…" for a file input."""
    return ",".join(f".{extension}" for extension in FORMATS)


def list_manuscripts(review):
    return review.manuscripts.prefetch_related("versions__file", "versions__created_by")


def _get(review, manuscript_id):
    return get_child(review.manuscripts, manuscript_id, label="Manuscript")


def get_version(review, version_id, manuscript_id=None):
    """A version of one of the review's manuscripts (of ``manuscript_id`` when given)."""
    versions = ManuscriptVersion.objects.filter(manuscript__review=review).select_related("manuscript", "file")
    if manuscript_id is not None:
        versions = versions.filter(manuscript_id=manuscript_id)
    return get_child(versions, version_id, label="Version")


def _clean_name(review, name, manuscript=None):
    require(name, field="name")
    name = check_length(name.strip(), 100, field="name")
    others = review.manuscripts.exclude(pk=getattr(manuscript, "pk", None))
    if others.filter(name__iexact=name).exists():
        raise ValidationError(f"The review already has a manuscript named {history.quote(name)}.", field="name")
    return name


@transaction.atomic
def add_manuscript(*, review, name, description="", actor=None):
    manuscript = Manuscript.objects.create(
        review=review,
        name=_clean_name(review, name),
        description=check_length((description or "").strip(), 500, field="description"),
        order=review.manuscripts.count(),
        created_by=actor,
    )
    MANUSCRIPT.added(review, manuscript, actor=actor)
    return manuscript


@transaction.atomic
def update_manuscript(*, review, manuscript_id, name=None, description=None):
    manuscript = _get(review, manuscript_id)
    tracker = MANUSCRIPT.track(manuscript)
    if name is not None:
        manuscript.name = _clean_name(review, name, manuscript)
    if description is not None:
        manuscript.description = check_length(description.strip(), 500, field="description")
    manuscript.save()
    MANUSCRIPT.changed(review, tracker)
    return manuscript


def remove_manuscript(*, review, manuscript_id):
    """Delete the manuscript with every version of it (their files too)."""
    manuscript = _get(review, manuscript_id)
    versions = [
        f"v{version.number}: {version.file.filename}" for version in manuscript.versions.select_related("file")
    ]
    suffix = f" and its {history.plural(len(versions), 'version')}" if versions else ""
    MANUSCRIPT.removed(review, manuscript, suffix=suffix, items=versions)
    manuscript.delete()


# Versions ------------------------------------------------------------------------------------------------------------


def _extension(filename):
    name = re.split(r"[\\/]", str(filename or ""))[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _clean_filename(filename, manuscript, number, extension):
    name = re.split(r"[\\/]", str(filename or ""))[-1]  # browsers on Windows may send the whole path
    name = "".join(char for char in name if char.isprintable()).strip()
    stem = name[: -len(extension) - 1] if name.lower().endswith(f".{extension}") else name
    return f"{stem[:200] or f'{manuscript.name} v{number}'}.{extension}"


def _inspect(file, extension):
    """Size and SHA-256 of the file, refusing one too big, empty, or whose content is not what its extension says."""
    limit = max_size_mb() * 1024 * 1024
    if file.size is not None and file.size > limit:
        raise ValidationError(f"The file must be at most {max_size_mb()} MB.", field="file")
    digest, size, head, text = hashlib.sha256(), 0, b"", extension == "tex"
    for chunk in file.chunks():
        size += len(chunk)
        if size > limit:
            raise ValidationError(f"The file must be at most {max_size_mb()} MB.", field="file")
        if len(head) < full_texts.SIGNATURE_WINDOW:
            head += chunk[: full_texts.SIGNATURE_WINDOW - len(head)]
        if text and b"\0" in chunk:
            text = None  # binary: not a LaTeX source
        digest.update(chunk)
    if not size:
        raise ValidationError("The file is empty.", field="file")
    matches = {
        "pdf": full_texts.PDF_SIGNATURE in head,
        "docx": head.startswith(ZIP_SIGNATURE),
        "odt": head.startswith(ZIP_SIGNATURE),
        "zip": head.startswith(ZIP_SIGNATURE),
        "tex": text is True,
    }[extension]
    if not matches:
        raise ValidationError(f"The file is not a {FORMATS[extension][1]}, as its name says.", field="file")
    file.seek(0)
    return size, digest.hexdigest()


def add_version(*, review, manuscript_id, file, filename=None, notes="", actor=None):
    """
    Keep ``file`` (an upload or any binary file object) as the manuscript's next version: a PDF, a Word or
    OpenDocument text, a LaTeX source or a ZIP, up to PARSIFAL_PDF_MAX_MB. ``notes``: what changed in it.
    """
    manuscript = _get(review, manuscript_id)
    if not isinstance(file, File):
        file = File(file)
    filename = filename or file.name
    extension = _extension(filename)
    if extension not in FORMATS:
        raise ValidationError(
            f"Upload a PDF, a Word (.docx) or OpenDocument (.odt) text, a LaTeX source (.tex) or a ZIP; not "
            f"{history.quote(filename or 'this file')}.",
            field="file",
        )
    notes = check_length((notes or "").strip(), 500, field="notes")
    size, sha256 = _inspect(file, extension)
    storage = files_storage()
    key = storage.save(f"reviews/{review.pk}/manuscripts/{uuid.uuid4().hex}.{extension}", file)
    try:
        with transaction.atomic():
            manuscript = Manuscript.objects.select_for_update().get(pk=manuscript.pk)
            number = max(manuscript.last_version, manuscript.versions.aggregate(last=Max("number"))["last"] or 0) + 1
            manuscript.last_version = number
            manuscript.save(update_fields=["last_version"])
            version = ManuscriptVersion.objects.create(
                manuscript=manuscript,
                number=number,
                file=StoredFile.objects.create(
                    key=key,
                    filename=_clean_filename(filename, manuscript, number, extension),
                    content_type=FORMATS[extension][0],
                    size=size,
                    sha256=sha256,
                    uploaded_by=actor,
                ),
                notes=notes,
                created_by=actor,
            )
    except Exception:
        storage.delete(key)
        raise
    _record_version(review, version, history.ADDED, "Uploaded", actor)
    return version


def _record_version(review, version, action, verb, actor=None):
    changes = (
        [history.change("Notes", "", version.notes, "notes")] if version.notes and action == history.ADDED else ()
    )
    history.record(
        review,
        ReviewEvent.REPORTING,
        action,
        f"{verb} version {version.number} of the manuscript {history.quote(version.manuscript.name)}",
        subject="manuscript",
        subject_id=version.manuscript_id,
        changes=changes,
        items=[version.file.filename],
        actor=actor,
    )


def remove_version(*, review, version_id, manuscript_id=None):
    """Delete one version of a manuscript and its file; the others keep their numbers, and its number is not reused."""
    version = get_version(review, version_id, manuscript_id)
    _record_version(review, version, history.REMOVED, "Removed")
    version.delete()
