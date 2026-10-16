"""
Personal library: folders and BibTeX documents owned by one user. Every function takes the owner first and only
ever touches that user's objects, so a document or folder of another user answers NotFound.
"""

from dataclasses import dataclass, field as dataclass_field

from django.db import transaction
from django.db.models import Count

from parsifal.apps.core.exceptions import Conflict, NotFound, ValidationError
from parsifal.apps.library.models import Document, Folder
from parsifal.apps.reviews.services._common import check_length, require
from parsifal.apps.reviews.services.studies import parse_bibtex

DOCUMENT_FIELDS = (
    "entry_type",
    "bibtexkey",
    "title",
    "author",
    "abstract",
    "keywords",
    "year",
    "month",
    "booktitle",
    "editor",
    "howpublished",
    "journal",
    "url",
    "publisher",
    "pages",
    "number",
    "volume",
    "edition",
    "chapter",
    "address",
    "crossref",
    "institution",
    "organization",
    "school",
    "series",
    "language",
    "coden",
    "doi",
    "isbn",
    "issn",
    "note",
    "publication_type",
)
FIELD_LIMITS = {name: Document._meta.get_field(name).max_length for name in DOCUMENT_FIELDS}
ENTRY_TYPES = dict(Document.ENTRY_TYPES)
ORDERINGS = ("title", "-title", "author", "-author", "year", "-year", "created_at", "-created_at")

# BibTeX keys mapped onto Document fields; the first key present wins (same convention as studies.import_bibtex).
BIBTEX_FIELD_ALIASES = {
    "bibtexkey": ("ID",),
    "entry_type": ("ENTRYTYPE",),
    "address": ("address", "correspondence_address1"),
    "author": ("authors", "author"),
    "publication_type": ("document_type", "publication_type"),
    "keywords": ("author_keywords", "keywords"),
    "url": ("url", "link"),
}
for _name in DOCUMENT_FIELDS:
    BIBTEX_FIELD_ALIASES.setdefault(_name, (_name,))


@dataclass
class ImportResult:
    imported: int = 0
    warnings: list = dataclass_field(default_factory=list)
    documents: list = dataclass_field(default_factory=list)
    folder: Folder | None = None


# Folders ------------------------------------------------------------------------------------------------------------


def list_folders(user):
    return Folder.objects.filter(user=user).annotate(document_count=Count("documents")).order_by("name")


def get_folder(user, folder_id):
    try:
        return Folder.objects.get(pk=folder_id, user=user)
    except (Folder.DoesNotExist, ValueError, TypeError):
        raise NotFound(f"Folder {folder_id!r} not found.")


def _clean_folder_name(name):
    name = require(name, field="name").strip()
    return check_length(name, 50, field="name")


def create_folder(user, *, name):
    name = _clean_folder_name(name)
    if Folder.objects.filter(user=user, name=name).exists():
        raise Conflict("Folder with this name already exists.", field="name")
    return Folder.objects.create(user=user, name=name)


def rename_folder(user, *, folder_id, name):
    folder = get_folder(user, folder_id)
    name = _clean_folder_name(name)
    if Folder.objects.filter(user=user, name=name).exclude(pk=folder.pk).exists():
        raise Conflict("Folder with this name already exists.", field="name")
    folder.name = name
    folder.save()
    return folder


def delete_folder(user, *, folder_id):
    """Delete the folder; its documents stay in the library."""
    get_folder(user, folder_id).delete()


# Documents ----------------------------------------------------------------------------------------------------------


def list_documents(user, *, folder_id=None, query=None, order="title"):
    if folder_id is not None:
        queryset = get_folder(user, folder_id).documents.all()
    else:
        queryset = Document.objects.filter(user=user)
    if query:
        queryset = queryset.filter(title__icontains=query)
    order = order or "title"
    if order not in ORDERINGS:
        raise ValidationError(f"order must be one of {ORDERINGS}.", field="order")
    return queryset.prefetch_related("folder_set").order_by(order, "pk")


def get_document(user, document_id):
    try:
        return Document.objects.prefetch_related("folder_set").get(pk=document_id, user=user)
    except (Document.DoesNotExist, ValueError, TypeError):
        raise NotFound(f"Document {document_id!r} not found.")


def get_documents(user, document_ids):
    """Several documents of the user by id; every id must exist."""
    document_ids = list(dict.fromkeys(document_ids))
    documents = list(Document.objects.filter(user=user, pk__in=document_ids))
    if len(documents) != len(document_ids):
        found = {document.pk for document in documents}
        raise NotFound(f"Document {[pk for pk in document_ids if pk not in found]} not found.")
    return documents


def _clean_fields(fields):
    cleaned = {}
    for name, value in fields.items():
        if name not in FIELD_LIMITS:
            raise ValidationError(f"Unknown document field {name!r}.", field=name)
        if value is not None:
            value = check_length(str(value).strip(), FIELD_LIMITS[name], field=name) or None
        if name == "entry_type" and value is not None:
            value = value.lower()
            if value not in ENTRY_TYPES:
                raise ValidationError(f"entry_type must be one of {sorted(ENTRY_TYPES)}.", field="entry_type")
        cleaned[name] = value
    return cleaned


def create_document(user, **fields):
    cleaned = _clean_fields(fields)
    if not any(cleaned.get(name) for name in ("title", "bibtexkey", "doi")):
        raise ValidationError("Provide at least a title, a bibtexkey or a doi.", field="title")
    return Document.objects.create(user=user, **cleaned)


def update_document(user, *, document_id, **fields):
    document = get_document(user, document_id)
    for name, value in _clean_fields(fields).items():
        setattr(document, name, value)
    document.save()
    return document


def delete_documents(user, *, document_ids):
    documents = get_documents(user, document_ids)
    Document.objects.filter(pk__in=[document.pk for document in documents]).delete()
    return len(documents)


# Folder membership --------------------------------------------------------------------------------------------------


def add_to_folder(user, *, folder_id, document_ids):
    folder = get_folder(user, folder_id)
    folder.documents.add(*get_documents(user, document_ids))
    return folder


def remove_from_folder(user, *, folder_id, document_ids):
    folder = get_folder(user, folder_id)
    folder.documents.remove(*get_documents(user, document_ids))
    return folder


@transaction.atomic
def move_documents(user, *, from_folder_id, to_folder_id, document_ids):
    """Move documents between two folders of the user; returns the destination folder."""
    source = get_folder(user, from_folder_id)
    destination = get_folder(user, to_folder_id)
    documents = get_documents(user, document_ids)
    destination.documents.add(*documents)
    if source.pk != destination.pk:
        source.documents.remove(*documents)
    return destination


# BibTeX import ------------------------------------------------------------------------------------------------------


def document_from_entry(entry, *, user, warnings=None):
    """Build an unsaved Document from one bibtexparser entry, truncating over-long values with a warning."""
    document = Document(user=user)
    key = entry.get("ID", "<no key>")
    for name in DOCUMENT_FIELDS:
        for alias in BIBTEX_FIELD_ALIASES[name]:
            if alias in entry:
                value = entry[alias]
                if name == "entry_type":
                    value = value.lower()
                    if value not in ENTRY_TYPES:
                        if warnings is not None:
                            warnings.append(f"{key}: unknown entry type {value!r} ignored.")
                        value = None
                elif len(value) > FIELD_LIMITS[name]:
                    value = value[: FIELD_LIMITS[name]]
                    if warnings is not None:
                        warnings.append(f"{key}: {name} truncated to {FIELD_LIMITS[name]} characters.")
                setattr(document, name, value)
                break
    return document


@transaction.atomic
def import_bibtex(user, *, content, folder_id=None):
    """Create one Document per BibTeX entry, optionally adding them all to a folder of the user."""
    folder = get_folder(user, folder_id) if folder_id is not None else None
    result = ImportResult(folder=folder)
    for entry in parse_bibtex(content):
        document = document_from_entry(entry, user=user, warnings=result.warnings)
        document.save()
        result.documents.append(document)
    result.imported = len(result.documents)
    if folder is not None and result.documents:
        folder.documents.add(*result.documents)
    return result
