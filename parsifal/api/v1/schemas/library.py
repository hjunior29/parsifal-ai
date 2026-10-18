from ninja import ModelSchema, Schema

from parsifal.apps.library.models import Document


class FolderOut(Schema):
    id: int
    name: str
    slug: str
    document_count: int

    @staticmethod
    def resolve_document_count(obj):
        # list_folders annotates the count; single objects compute it.
        return getattr(obj, "document_count", None) or obj.documents.count()


class FolderIn(Schema):
    name: str


class IdsIn(Schema):
    ids: list[int]


class MoveIn(Schema):
    ids: list[int]
    to_folder_id: int


class DocumentOut(ModelSchema):
    folder_ids: list[int]

    class Meta:
        model = Document
        exclude = ("user", "review", "shared_folder")

    @staticmethod
    def resolve_folder_ids(obj):
        return sorted(folder.pk for folder in obj.folder_set.all())


class DocumentIn(Schema):
    """BibTeX fields of a document; every field is optional and ``None`` clears it on update."""

    entry_type: str | None = None
    bibtexkey: str | None = None
    title: str | None = None
    author: str | None = None
    abstract: str | None = None
    keywords: str | None = None
    year: str | None = None
    month: str | None = None
    booktitle: str | None = None
    editor: str | None = None
    howpublished: str | None = None
    journal: str | None = None
    url: str | None = None
    publisher: str | None = None
    pages: str | None = None
    number: str | None = None
    volume: str | None = None
    edition: str | None = None
    chapter: str | None = None
    address: str | None = None
    crossref: str | None = None
    institution: str | None = None
    organization: str | None = None
    school: str | None = None
    series: str | None = None
    language: str | None = None
    coden: str | None = None
    doi: str | None = None
    isbn: str | None = None
    issn: str | None = None
    note: str | None = None
    publication_type: str | None = None


class LibraryImportIn(Schema):
    bibtex: str
    folder_id: int | None = None


class LibraryImportOut(Schema):
    imported: int
    failed: int = 0
    warnings: list[str]
    document_ids: list[int]
    folder_id: int | None = None
