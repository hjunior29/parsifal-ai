"""Personal library: folders, BibTeX documents and imports. Everything is scoped to the authenticated user."""

from ninja import File, Form, Router, UploadedFile
from ninja.pagination import LimitOffsetPagination, paginate

from parsifal.api.v1.schemas.common import CountOut
from parsifal.api.v1.schemas.library import (
    DocumentIn,
    DocumentOut,
    FolderIn,
    FolderOut,
    IdsIn,
    LibraryImportIn,
    LibraryImportOut,
    MoveIn,
)
from parsifal.apps.library import services as library

router = Router(tags=["library"])


# Folders ------------------------------------------------------------------------------------------------------------


@router.get("/library/folders", response=list[FolderOut], operation_id="folders_list")
def folders_list(request):
    return library.list_folders(request.auth)


@router.post("/library/folders", response={201: FolderOut}, operation_id="folders_create")
def folders_create(request, payload: FolderIn):
    return 201, library.create_folder(request.auth, name=payload.name)


@router.patch("/library/folders/{int:folder_id}", response=FolderOut, operation_id="folders_rename")
def folders_rename(request, folder_id: int, payload: FolderIn):
    return library.rename_folder(request.auth, folder_id=folder_id, name=payload.name)


@router.delete("/library/folders/{int:folder_id}", response={204: None}, operation_id="folders_delete")
def folders_delete(request, folder_id: int):
    """Delete the folder; its documents stay in the library."""
    library.delete_folder(request.auth, folder_id=folder_id)
    return 204, None


@router.post("/library/folders/{int:folder_id}/documents", response=FolderOut, operation_id="folders_add_documents")
def folders_add_documents(request, folder_id: int, payload: IdsIn):
    """Add documents to the folder (a document can be in several folders)."""
    return library.add_to_folder(request.auth, folder_id=folder_id, document_ids=payload.ids)


@router.post(
    "/library/folders/{int:folder_id}/documents/remove", response=FolderOut, operation_id="folders_remove_documents"
)
def folders_remove_documents(request, folder_id: int, payload: IdsIn):
    """Take documents out of the folder without deleting them."""
    return library.remove_from_folder(request.auth, folder_id=folder_id, document_ids=payload.ids)


@router.post(
    "/library/folders/{int:folder_id}/documents/move", response=FolderOut, operation_id="folders_move_documents"
)
def folders_move_documents(request, folder_id: int, payload: MoveIn):
    """Move documents from this folder to ``to_folder_id``; answers the destination folder."""
    return library.move_documents(
        request.auth, from_folder_id=folder_id, to_folder_id=payload.to_folder_id, document_ids=payload.ids
    )


# Documents ----------------------------------------------------------------------------------------------------------


@router.get("/library/documents", response=list[DocumentOut], operation_id="documents_list")
@paginate(LimitOffsetPagination)
def documents_list(request, folder_id: int | None = None, q: str | None = None, order: str | None = None):
    """Documents of your library; ``order`` is title, author, year or created_at, optionally prefixed with ``-``."""
    return library.list_documents(request.auth, folder_id=folder_id, query=q, order=order)


@router.post("/library/documents", response={201: DocumentOut}, operation_id="documents_create")
def documents_create(request, payload: DocumentIn):
    return 201, library.create_document(request.auth, **payload.dict(exclude_unset=True))


@router.get("/library/documents/{int:document_id}", response=DocumentOut, operation_id="documents_get")
def documents_get(request, document_id: int):
    return library.get_document(request.auth, document_id)


@router.patch("/library/documents/{int:document_id}", response=DocumentOut, operation_id="documents_update")
def documents_update(request, document_id: int, payload: DocumentIn):
    """Change the given fields only; send ``null`` to clear one."""
    return library.update_document(request.auth, document_id=document_id, **payload.dict(exclude_unset=True))


@router.delete("/library/documents/{int:document_id}", response={204: None}, operation_id="documents_delete")
def documents_delete(request, document_id: int):
    library.delete_documents(request.auth, document_ids=[document_id])
    return 204, None


@router.post("/library/documents/delete", response=CountOut, operation_id="documents_delete_batch")
def documents_delete_batch(request, payload: IdsIn):
    """Delete several documents at once."""
    return CountOut(count=library.delete_documents(request.auth, document_ids=payload.ids))


# Import -------------------------------------------------------------------------------------------------------------


def _import_out(result):
    return LibraryImportOut(
        imported=result.imported,
        warnings=result.warnings,
        document_ids=[document.pk for document in result.documents],
        folder_id=result.folder.pk if result.folder else None,
    )


@router.post("/library/import", response={201: LibraryImportOut}, operation_id="library_import")
def library_import(request, payload: LibraryImportIn):
    """Import BibTeX text into the library, optionally into a folder."""
    result = library.import_bibtex(request.auth, content=payload.bibtex, folder_id=payload.folder_id)
    return 201, _import_out(result)


@router.post("/library/import/file", response={201: LibraryImportOut}, operation_id="library_import_file")
def library_import_file(request, file: File[UploadedFile], folder_id: Form[int | None] = None):
    """Upload a .bib file into the library (multipart form: ``file`` and optional ``folder_id``)."""
    result = library.import_bibtex(request.auth, content=file.read(), folder_id=folder_id)
    return 201, _import_out(result)
