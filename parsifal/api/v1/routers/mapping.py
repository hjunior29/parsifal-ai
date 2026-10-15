"""Systematic mapping studies: classification facets, article classification, test set, process checklist."""

from ninja import Router

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.common import OrderIn
from parsifal.api.v1.schemas.mapping import (
    ArticleClassificationOut,
    CategoryIn,
    CategoryOut,
    CategoryUpdateIn,
    ChecklistItemIn,
    ChecklistOut,
    ClassificationIn,
    FacetClassificationOut,
    FacetFrequenciesOut,
    FacetIn,
    FacetMatrixOut,
    FacetOut,
    FacetTemplateOut,
    FacetUpdateIn,
    TestSetItemIn,
    TestSetItemOut,
    TestSetItemUpdateIn,
    TestSetReportOut,
)
from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.services import classification, mapping

router = Router(tags=["mapping"])


# ---------------------------------------------------------------------------------------------------------------------
# Facets and categories
# ---------------------------------------------------------------------------------------------------------------------


@router.get("/facets/templates", response=list[FacetTemplateOut], operation_id="facet_templates")
def facet_templates(request):
    """Topic-independent classification schemes recommended by the guidelines."""
    return classification.list_templates()


@router.get("/reviews/{int:review_id}/facets", response=list[FacetOut], operation_id="facets_list")
def facets_list(request, review_id: int):
    return get_review(request, review_id).facets.prefetch_related("categories")


@router.post("/reviews/{int:review_id}/facets", response={201: FacetOut}, operation_id="facets_create")
def facets_create(request, review_id: int, payload: FacetIn):
    """Create a facet from a template or a custom one (name + optional categories)."""
    review = get_review(request, review_id)
    if payload.template:
        return 201, classification.add_facet_from_template(review=review, template=payload.template)
    if not payload.name:
        raise ValidationError("Provide template or name.")
    facet = classification.add_facet(
        review=review,
        name=payload.name,
        kind=payload.kind,
        description=payload.description,
        multiple=payload.multiple,
        categories=payload.categories,
    )
    return 201, facet


@router.patch("/reviews/{int:review_id}/facets/{int:facet_id}", response=FacetOut, operation_id="facets_update")
def facets_update(request, review_id: int, facet_id: int, payload: FacetUpdateIn):
    review = get_review(request, review_id)
    return classification.update_facet(review=review, facet_id=facet_id, **payload.dict(exclude_unset=True))


@router.delete("/reviews/{int:review_id}/facets/{int:facet_id}", response={204: None}, operation_id="facets_delete")
def facets_delete(request, review_id: int, facet_id: int):
    classification.remove_facet(review=get_review(request, review_id), facet_id=facet_id)
    return 204, None


@router.put("/reviews/{int:review_id}/facets/order", response=list[FacetOut], operation_id="facets_reorder")
def facets_reorder(request, review_id: int, payload: OrderIn):
    return classification.reorder_facets(review=get_review(request, review_id), ordered_ids=payload.ids)


@router.post(
    "/reviews/{int:review_id}/facets/{int:facet_id}/categories",
    response={201: CategoryOut},
    operation_id="categories_create",
)
def categories_create(request, review_id: int, facet_id: int, payload: CategoryIn):
    review = get_review(request, review_id)
    category = classification.add_category(
        review=review, facet_id=facet_id, name=payload.name, description=payload.description
    )
    return 201, category


@router.patch(
    "/reviews/{int:review_id}/facets/{int:facet_id}/categories/{int:category_id}",
    response=CategoryOut,
    operation_id="categories_update",
)
def categories_update(request, review_id: int, facet_id: int, category_id: int, payload: CategoryUpdateIn):
    review = get_review(request, review_id)
    return classification.update_category(
        review=review, facet_id=facet_id, category_id=category_id, **payload.dict(exclude_unset=True)
    )


@router.delete(
    "/reviews/{int:review_id}/facets/{int:facet_id}/categories/{int:category_id}",
    response={204: None},
    operation_id="categories_delete",
)
def categories_delete(request, review_id: int, facet_id: int, category_id: int):
    classification.remove_category(review=get_review(request, review_id), facet_id=facet_id, category_id=category_id)
    return 204, None


@router.put(
    "/reviews/{int:review_id}/facets/{int:facet_id}/categories/order",
    response=list[CategoryOut],
    operation_id="categories_reorder",
)
def categories_reorder(request, review_id: int, facet_id: int, payload: OrderIn):
    review = get_review(request, review_id)
    return classification.reorder_categories(review=review, facet_id=facet_id, ordered_ids=payload.ids)


# ---------------------------------------------------------------------------------------------------------------------
# Classifying articles
# ---------------------------------------------------------------------------------------------------------------------


def _classification_out(review, article_id):
    rows = classification.article_classifications(review=review, article_id=article_id)
    return ArticleClassificationOut(
        article_id=article_id,
        facets=[
            FacetClassificationOut(
                facet_id=row["facet"].pk,
                facet=row["facet"].name,
                multiple=row["facet"].multiple,
                category_ids=[c.pk for c in row["categories"]],
                categories=[c.name for c in row["categories"]],
                notes=row["notes"],
                user=row["user"].username if row["user"] else None,
            )
            for row in rows
        ],
    )


@router.get(
    "/reviews/{int:review_id}/articles/{int:article_id}/classification",
    response=ArticleClassificationOut,
    operation_id="article_classification_get",
)
def article_classification_get(request, review_id: int, article_id: int):
    return _classification_out(get_review(request, review_id), article_id)


@router.put(
    "/reviews/{int:review_id}/articles/{int:article_id}/classification",
    response=ArticleClassificationOut,
    operation_id="article_classification_set",
)
def article_classification_set(request, review_id: int, article_id: int, payload: ClassificationIn):
    """Set the categories of one facet for the article (empty list clears it)."""
    review = get_review(request, review_id)
    classification.classify(
        review=review,
        article_id=article_id,
        facet_id=payload.facet_id,
        category_ids=payload.category_ids,
        actor=request.auth,
        notes=payload.notes,
    )
    return _classification_out(review, article_id)


@router.get(
    "/reviews/{int:review_id}/analytics/facets/{int:facet_id}/frequencies",
    response=FacetFrequenciesOut,
    operation_id="analytics_facet_frequencies",
)
def analytics_facet_frequencies(request, review_id: int, facet_id: int):
    """Number of final-selection articles per category of a facet."""
    return classification.facet_frequencies(review=get_review(request, review_id), facet_id=facet_id)


@router.get(
    "/reviews/{int:review_id}/analytics/facet-matrix", response=FacetMatrixOut, operation_id="analytics_facet_matrix"
)
def analytics_facet_matrix(request, review_id: int, rows: int, columns: int):
    """Counts per (row category, column category) of two facets — bubble-plot data."""
    review = get_review(request, review_id)
    return classification.facet_matrix(review=review, row_facet_id=rows, column_facet_id=columns)


# ---------------------------------------------------------------------------------------------------------------------
# Test set of known papers
# ---------------------------------------------------------------------------------------------------------------------


@router.get("/reviews/{int:review_id}/test-set", response=TestSetReportOut, operation_id="test_set_get")
def test_set_get(request, review_id: int):
    return mapping.test_set_report(get_review(request, review_id))


@router.post("/reviews/{int:review_id}/test-set", response={201: TestSetItemOut}, operation_id="test_set_add")
def test_set_add(request, review_id: int, payload: TestSetItemIn):
    review = get_review(request, review_id)
    return 201, mapping.add_test_set_article(review=review, title=payload.title, doi=payload.doi, notes=payload.notes)


@router.patch(
    "/reviews/{int:review_id}/test-set/{int:item_id}", response=TestSetItemOut, operation_id="test_set_update"
)
def test_set_update(request, review_id: int, item_id: int, payload: TestSetItemUpdateIn):
    review = get_review(request, review_id)
    return mapping.update_test_set_article(review=review, item_id=item_id, **payload.dict(exclude_unset=True))


@router.delete("/reviews/{int:review_id}/test-set/{int:item_id}", response={204: None}, operation_id="test_set_delete")
def test_set_delete(request, review_id: int, item_id: int):
    mapping.remove_test_set_article(review=get_review(request, review_id), item_id=item_id)
    return 204, None


@router.post("/reviews/{int:review_id}/test-set/match", response=TestSetReportOut, operation_id="test_set_match")
def test_set_match(request, review_id: int):
    """Re-match the known papers against the imported articles (by DOI, then by normalised title)."""
    return mapping.match_test_set(review=get_review(request, review_id))


# ---------------------------------------------------------------------------------------------------------------------
# Process checklist
# ---------------------------------------------------------------------------------------------------------------------


@router.get("/reviews/{int:review_id}/checklist", response=ChecklistOut, operation_id="checklist_get")
def checklist_get(request, review_id: int):
    """Petersen et al. (2015) Table 8 actions with the ones applied in this review."""
    return mapping.checklist(get_review(request, review_id))


@router.put("/reviews/{int:review_id}/checklist/{key}", response=ChecklistOut, operation_id="checklist_set")
def checklist_set(request, review_id: int, key: str, payload: ChecklistItemIn):
    review = get_review(request, review_id)
    return mapping.set_checklist_item(review=review, key=key, applied=payload.applied, notes=payload.notes)
