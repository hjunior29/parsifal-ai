from django.http import FileResponse

from ninja import File, Router, UploadedFile

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.review_backups import ReviewBackupOut
from parsifal.api.v1.schemas.reviews import ReviewOut
from parsifal.apps.reviews.services import review_backups

router = Router(tags=["review backups"])


@router.get("/reviews/{int:review_id}/backups", response=list[ReviewBackupOut], operation_id="reviews_backups_list")
def reviews_backups_list(request, review_id: int):
    """The review's backups kept on the server, newest first (only the main author)."""
    return list(review_backups.list_backups(get_review(request, review_id), request.auth))


@router.post(
    "/reviews/{int:review_id}/backups", response={201: ReviewBackupOut}, operation_id="reviews_backups_create"
)
def reviews_backups_create(request, review_id: int):
    """
    Back up the review on the server (only the main author): the protocol, sources and search strings, the studies
    and their PDFs, the reviewers' decisions, the AI screening runs, quality assessment, data extraction and
    classification, in one .tar.gz. The newest PARSIFAL_REVIEW_BACKUPS_KEEP (10 by default) are kept.
    """
    return 201, review_backups.create_backup(review=get_review(request, review_id), actor=request.auth)


@router.post(
    "/reviews/{int:review_id}/backups/upload",
    response={201: ReviewBackupOut},
    operation_id="reviews_backups_upload",
)
def reviews_backups_upload(request, review_id: int, file: File[UploadedFile]):
    """Add a backup file (multipart ``file``, downloaded before or from another Parsifal) to the list, once checked."""
    review = get_review(request, review_id)
    backup = review_backups.upload_backup(review=review, actor=request.auth, filename=file.name, content=file.read())
    return 201, backup


@router.get("/reviews/{int:review_id}/backups/{int:backup_id}/download", operation_id="reviews_backups_download")
def reviews_backups_download(request, review_id: int, backup_id: int):
    """The backup's .tar.gz."""
    backup = review_backups.get_backup(get_review(request, review_id), request.auth, backup_id)
    return FileResponse(
        backup.file.open(), content_type="application/gzip", as_attachment=True, filename=backup.file.filename
    )


@router.post(
    "/reviews/{int:review_id}/backups/{int:backup_id}/restore",
    response=ReviewOut,
    operation_id="reviews_backups_restore",
)
def reviews_backups_restore(request, review_id: int, backup_id: int):
    """
    Replace everything of the review with the backup (only the main author). What it has now is backed up first,
    into the list. The review keeps its name, main author, people and AI agents (with their tokens); people of the
    backup are matched by username (those without an account get an inactive one).
    """
    review = get_review(request, review_id)
    return review_backups.restore_backup(review=review, actor=request.auth, backup_id=backup_id)


@router.delete(
    "/reviews/{int:review_id}/backups/{int:backup_id}", response={204: None}, operation_id="reviews_backups_delete"
)
def reviews_backups_delete(request, review_id: int, backup_id: int):
    """Delete the backup and its file."""
    review_backups.delete_backup(review=get_review(request, review_id), actor=request.auth, backup_id=backup_id)
    return 204, None


@router.post("/reviews/import", response={201: ReviewOut}, operation_id="reviews_import")
def reviews_import(request, file: File[UploadedFile]):
    """
    A new review from a review backup (multipart ``file``), here or from another Parsifal, with you as its main
    author. Its people are matched by username: those without an account here get an inactive one, so their
    decisions stay theirs; AI agents come back as agents of the review, without tokens.
    """
    return 201, review_backups.import_review(actor=request.auth, content=file.read())
