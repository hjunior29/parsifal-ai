from ninja import Router

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.common import OrderIn
from parsifal.api.v1.schemas.extraction import (
    ArticleExtractionOut,
    DoneIn,
    ExtractedValueOut,
    FieldIn,
    FieldOut,
    FieldUpdateIn,
    ValueIn,
)
from parsifal.apps.reviews.services import extraction

router = Router(tags=["extraction"])


@router.get(
    "/reviews/{int:review_id}/extraction/fields", response=list[FieldOut], operation_id="extraction_fields_list"
)
def extraction_fields_list(request, review_id: int):
    return get_review(request, review_id).dataextractionfield_set.prefetch_related("dataextractionlookup_set")


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
    return extraction.reorder_fields(review=get_review(request, review_id), ordered_ids=payload.ids)


def _article_extraction(review, article_id):
    rows = extraction.article_values(review=review, article_id=article_id)
    article = review.article_set.get(pk=article_id)
    return ArticleExtractionOut(
        article_id=article.pk,
        finished_data_extraction=article.finished_data_extraction,
        values=[
            ExtractedValueOut(
                field_id=row["field"].pk,
                field=row["field"].description,
                field_type=row["field"].field_type,
                value=row["value"],
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
    """Set one field's value. Select-many fields take ``values`` (the complete list of lookup ids)."""
    review = get_review(request, review_id)
    extraction.set_value(
        review=review,
        article_id=article_id,
        field_id=payload.field_id,
        value=payload.value,
        values=payload.values,
        actor=request.auth,
    )
    return _article_extraction(review, article_id)


@router.put(
    "/reviews/{int:review_id}/articles/{int:article_id}/extraction/done",
    response=ArticleExtractionOut,
    operation_id="article_extraction_done",
)
def article_extraction_done(request, review_id: int, article_id: int, payload: DoneIn):
    review = get_review(request, review_id)
    extraction.mark_done(review=review, article_id=article_id, done=payload.done)
    return _article_extraction(review, article_id)
