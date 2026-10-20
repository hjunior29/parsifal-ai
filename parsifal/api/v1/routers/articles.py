from django.http import FileResponse

from ninja import File, Form, Router, UploadedFile
from ninja.pagination import LimitOffsetPagination, paginate

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.articles import (
    ArticleCreateIn,
    ArticleOut,
    ArticleUpdateIn,
    ClearIn,
    DuplicateGroupsOut,
    IdsIn,
    ImportIn,
    ImportOut,
    PdfOut,
    ResolveIn,
    StatusIn,
)
from parsifal.api.v1.schemas.common import CountOut
from parsifal.apps.reviews.services import full_texts, studies

router = Router(tags=["articles"])


@router.get("/reviews/{int:review_id}/articles", response=list[ArticleOut], operation_id="articles_list")
@paginate(LimitOffsetPagination)
def articles_list(
    request,
    review_id: int,
    source_id: int | None = None,
    status: str | None = None,
    q: str | None = None,
    finished_data_extraction: bool | None = None,
    starred: bool | None = None,
):
    """
    Articles of the review; ``status`` is U (unclassified), A (accepted), R (rejected) or D (duplicated); ``q``
    searches the title, DOI and BibTeX key (a DOI may be pasted as a doi.org link); ``starred=true`` keeps the
    starred ones (``false``, the others).
    """
    review = get_review(request, review_id)
    return studies.list_articles(
        review,
        source_id=source_id,
        status=status,
        query=q,
        finished_data_extraction=finished_data_extraction,
        starred=starred,
    ).select_related("created_by", "updated_by")


@router.post("/reviews/{int:review_id}/articles", response={201: ArticleOut}, operation_id="articles_create")
def articles_create(request, review_id: int, payload: ArticleCreateIn):
    review = get_review(request, review_id)
    data = payload.dict(exclude_unset=True)
    source_id = data.pop("source_id")
    return 201, studies.create_article(review=review, source_id=source_id, actor=request.auth, **data)


@router.get(
    "/reviews/{int:review_id}/articles/duplicates", response=DuplicateGroupsOut, operation_id="articles_duplicates"
)
def articles_duplicates(request, review_id: int):
    """
    Groups of non-duplicated articles that are the same publication (same normalised DOI or title, oldest first).
    ``details`` is aligned with ``groups`` and says why each was grouped and whether it needs a manual check;
    ``conflicts`` lists articles with the same title but different DOIs, which are not grouped.
    """
    groups, conflicts = studies.duplicate_report(get_review(request, review_id))
    return DuplicateGroupsOut(
        groups=[group.articles for group in groups],
        details=[
            dict(article_ids=[a.pk for a in g.articles], match=g.match, needs_review=g.needs_review, reason=g.reason)
            for g in groups
        ],
        conflicts=[dict(article_ids=[a.pk for a in c.articles], reason=c.reason) for c in conflicts],
    )


@router.post(
    "/reviews/{int:review_id}/articles/duplicates/resolve",
    response=list[ArticleOut],
    operation_id="articles_resolve_duplicates",
)
def articles_resolve_duplicates(request, review_id: int, payload: ResolveIn):
    """
    Mark the given ids as duplicated, or — without ids — every duplicate except the oldest of each group
    (groups flagged ``needs_review`` are skipped).
    """
    review = get_review(request, review_id)
    return studies.resolve_duplicates(review=review, article_ids=payload.ids, actor=request.auth)


@router.post("/reviews/{int:review_id}/articles/status", response=CountOut, operation_id="articles_set_status")
def articles_set_status(request, review_id: int, payload: StatusIn):
    """Bulk selection decision with an optional criteria (reason) and comments."""
    review = get_review(request, review_id)
    count = studies.set_status(
        review=review,
        article_ids=payload.ids,
        status=payload.status,
        selection_criteria_id=payload.selection_criteria_id,
        comments=payload.comments,
        actor=request.auth,
    )
    return CountOut(count=count)


def _import_out(result):
    return ImportOut(
        imported=result.imported,
        failed=result.failed,
        warnings=result.warnings,
        article_ids=[article.pk for article in result.articles],
    )


@router.post("/reviews/{int:review_id}/articles/import", response={201: ImportOut}, operation_id="articles_import")
def articles_import(request, review_id: int, payload: ImportIn):
    """Import BibTeX text into a source of the review."""
    review = get_review(request, review_id)
    result = studies.import_bibtex(
        review=review, source_id=payload.source_id, content=payload.bibtex, actor=request.auth
    )
    return 201, _import_out(result)


@router.post(
    "/reviews/{int:review_id}/articles/import/file", response={201: ImportOut}, operation_id="articles_import_file"
)
def articles_import_file(request, review_id: int, source_id: Form[int], file: File[UploadedFile]):
    """Import a .bib file (multipart form: ``source_id`` and ``file``)."""
    review = get_review(request, review_id)
    result = studies.import_bibtex(review=review, source_id=source_id, content=file.read(), actor=request.auth)
    return 201, _import_out(result)


@router.get("/reviews/{int:review_id}/articles/{int:article_id}", response=ArticleOut, operation_id="articles_get")
def articles_get(request, review_id: int, article_id: int):
    review = get_review(request, review_id)
    return studies.get_article(review=review, article_id=article_id)


@router.patch(
    "/reviews/{int:review_id}/articles/{int:article_id}", response=ArticleOut, operation_id="articles_update"
)
def articles_update(request, review_id: int, article_id: int, payload: ArticleUpdateIn):
    review = get_review(request, review_id)
    data = payload.dict(exclude_unset=True)
    return studies.update_article(review=review, article_id=article_id, actor=request.auth, **data)


@router.delete(
    "/reviews/{int:review_id}/articles/{int:article_id}", response={204: None}, operation_id="articles_delete"
)
def articles_delete(request, review_id: int, article_id: int):
    studies.delete_articles(review=get_review(request, review_id), article_ids=[article_id])
    return 204, None


@router.put(
    "/reviews/{int:review_id}/articles/{int:article_id}/star", response=ArticleOut, operation_id="articles_star"
)
def articles_star(request, review_id: int, article_id: int):
    """
    Star the study in this review: one mark per study, shared by every member, whatever its status. Starring it again
    keeps who starred it first; the status is untouched.
    """
    review = get_review(request, review_id)
    return studies.set_starred(review=review, article_id=article_id, starred=True, actor=request.auth)


@router.delete(
    "/reviews/{int:review_id}/articles/{int:article_id}/star", response=ArticleOut, operation_id="articles_unstar"
)
def articles_unstar(request, review_id: int, article_id: int):
    """Remove the study's star (whoever starred it)."""
    review = get_review(request, review_id)
    return studies.set_starred(review=review, article_id=article_id, starred=False, actor=request.auth)


@router.post(
    "/reviews/{int:review_id}/articles/{int:article_id}/pdf",
    response={201: PdfOut},
    operation_id="articles_pdf_upload",
)
def articles_pdf_upload(request, review_id: int, article_id: int, file: File[UploadedFile]):
    """
    Upload the study's full text (multipart form: ``file``), replacing the one it had. PDF only, up to
    PARSIFAL_PDF_MAX_MB (50 MB by default); any study may have one, whatever its status, and the status is untouched.
    """
    review = get_review(request, review_id)
    return 201, full_texts.attach_pdf(review=review, article_id=article_id, file=file, actor=request.auth)


@router.get("/reviews/{int:review_id}/articles/{int:article_id}/pdf", operation_id="articles_pdf_download")
def articles_pdf_download(request, review_id: int, article_id: int):
    """The study's PDF, with the name it was uploaded with (404 when it has none)."""
    pdf = full_texts.get_pdf(review=get_review(request, review_id), article_id=article_id)
    return FileResponse(pdf.open(), content_type=pdf.content_type, as_attachment=True, filename=pdf.filename)


@router.delete(
    "/reviews/{int:review_id}/articles/{int:article_id}/pdf", response={204: None}, operation_id="articles_pdf_delete"
)
def articles_pdf_delete(request, review_id: int, article_id: int):
    """Delete the study's PDF (404 when it has none)."""
    full_texts.remove_pdf(review=get_review(request, review_id), article_id=article_id)
    return 204, None


@router.post("/reviews/{int:review_id}/articles/delete", response=CountOut, operation_id="articles_delete_batch")
def articles_delete_batch(request, review_id: int, payload: IdsIn):
    """
    Delete several articles at once (all ids must belong to the review, otherwise nothing is deleted). Their
    decisions, quality assessments, extractions, classifications and PDFs are deleted with them.
    """
    return CountOut(count=studies.delete_articles(review=get_review(request, review_id), article_ids=payload.ids))


@router.post("/reviews/{int:review_id}/articles/clear", response=CountOut, operation_id="articles_clear")
def articles_clear(request, review_id: int, payload: ClearIn):
    """
    Delete every article imported into ``source_id`` (only those with ``status`` when given), keeping the source.
    Use it to undo an import of the wrong export.
    """
    review = get_review(request, review_id)
    return CountOut(count=studies.clear_articles(review=review, source_id=payload.source_id, status=payload.status))
