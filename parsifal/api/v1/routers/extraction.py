from ninja import Router
from ninja.pagination import LimitOffsetPagination, paginate

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.common import OrderIn
from parsifal.api.v1.schemas.extraction import (
    ArticleExtractionOut,
    DoneIn,
    EvidenceIn,
    ExtractedValueOut,
    ExtractionStudyOut,
    FieldIn,
    FieldOut,
    FieldUpdateIn,
    ValueIn,
)
from parsifal.apps.reviews.services import codes, extraction

router = Router(tags=["extraction"])


@router.get(
    "/reviews/{int:review_id}/extraction/fields", response=list[FieldOut], operation_id="extraction_fields_list"
)
def extraction_fields_list(request, review_id: int):
    """The fields in their order, each with its code (EX01…)."""
    return codes.fields(get_review(request, review_id))


@router.post(
    "/reviews/{int:review_id}/extraction/fields", response={201: FieldOut}, operation_id="extraction_fields_create"
)
def extraction_fields_create(request, review_id: int, payload: FieldIn):
    review = get_review(request, review_id)
    field = extraction.add_field(
        review=review,
        description=payload.description,
        field_type=payload.field_type,
        lookup_values=payload.lookup_values,
    )
    return 201, field


@router.patch(
    "/reviews/{int:review_id}/extraction/fields/{int:field_id}",
    response=FieldOut,
    operation_id="extraction_fields_update",
)
def extraction_fields_update(request, review_id: int, field_id: int, payload: FieldUpdateIn):
    review = get_review(request, review_id)
    return extraction.update_field(review=review, field_id=field_id, **payload.dict(exclude_unset=True))


@router.delete(
    "/reviews/{int:review_id}/extraction/fields/{int:field_id}",
    response={204: None},
    operation_id="extraction_fields_delete",
)
def extraction_fields_delete(request, review_id: int, field_id: int):
    extraction.remove_field(review=get_review(request, review_id), field_id=field_id)
    return 204, None


@router.put(
    "/reviews/{int:review_id}/extraction/fields/order",
    response=list[FieldOut],
    operation_id="extraction_fields_reorder",
)
def extraction_fields_reorder(request, review_id: int, payload: OrderIn):
    review = get_review(request, review_id)
    extraction.reorder_fields(review=review, ordered_ids=payload.ids)
    return codes.fields(review)


@router.get(
    "/reviews/{int:review_id}/extraction/studies",
    response=list[ExtractionStudyOut],
    operation_id="extraction_studies",
)
@paginate(LimitOffsetPagination)
def extraction_studies(request, review_id: int, q: str | None = None, done: bool | None = None):
    """
    The studies of the final selection, the ones to extract data from, as Data Extraction lists them (by title): each
    with its quality score, how many fields have a value and how many of those have no evidence. ``q`` searches the
    title; ``done``: only the studies marked as done (true) or the others (false).
    """
    return extraction.extraction_list(get_review(request, review_id), query=q, done=done)


def _article_extraction(review, article_id):
    rows = extraction.article_values(review=review, article_id=article_id)
    article = review.article_set.get(pk=article_id)
    field_codes = {field.pk: field.code for field in codes.fields(review)}
    return ArticleExtractionOut(
        article_id=article.pk,
        finished_data_extraction=article.finished_data_extraction,
        values=[
            ExtractedValueOut(
                field_id=row["field"].pk,
                code=field_codes.get(row["field"].pk, ""),
                field=row["field"].description,
                field_type=row["field"].field_type,
                value=row["value"],
                evidence=row["evidence"],
                needs_evidence=row["needs_evidence"],
            )
            for row in rows
        ],
    )


@router.get(
    "/reviews/{int:review_id}/articles/{int:article_id}/extraction",
    response=ArticleExtractionOut,
    operation_id="article_extraction_get",
)
def article_extraction_get(request, review_id: int, article_id: int):
    return _article_extraction(get_review(request, review_id), article_id)


@router.put(
    "/reviews/{int:review_id}/articles/{int:article_id}/extraction",
    response=ArticleExtractionOut,
    operation_id="article_extraction_set",
)
def article_extraction_set(request, review_id: int, article_id: int, payload: ValueIn):
    """
    Set one field's value, and its evidence (where the study supports it). Select-many fields take ``values`` (the
    complete list of lookup ids). A study is marked as done only when each value has its evidence.
    """
    review = get_review(request, review_id)
    extraction.set_value(
        review=review,
        article_id=article_id,
        field_id=payload.field_id,
        value=payload.value,
        values=payload.values,
        evidence=payload.evidence,
        actor=request.auth,
    )
    return _article_extraction(review, article_id)


@router.put(
    "/reviews/{int:review_id}/articles/{int:article_id}/extraction/evidence",
    response=ArticleExtractionOut,
    operation_id="article_extraction_evidence",
)
def article_extraction_evidence(request, review_id: int, article_id: int, payload: EvidenceIn):
    """Set the evidence of one field's value, leaving the value as it is (empty clears it)."""
    review = get_review(request, review_id)
    extraction.set_evidence(
        review=review,
        article_id=article_id,
        field_id=payload.field_id,
        evidence=payload.evidence,
        actor=request.auth,
    )
    return _article_extraction(review, article_id)


@router.put(
    "/reviews/{int:review_id}/articles/{int:article_id}/extraction/done",
    response=ArticleExtractionOut,
    operation_id="article_extraction_done",
)
def article_extraction_done(request, review_id: int, article_id: int, payload: DoneIn):
    """Mark the study's extraction as done (or not); refused while a value has no evidence."""
    review = get_review(request, review_id)
    extraction.mark_done(review=review, article_id=article_id, done=payload.done)
    return _article_extraction(review, article_id)
