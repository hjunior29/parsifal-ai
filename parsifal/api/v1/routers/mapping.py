"""Optional steps of any review: the test set of known papers and the process checklists."""

from ninja import Router

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.mapping import (
    ChecklistItemIn,
    ChecklistOut,
    TestSetItemIn,
    TestSetItemOut,
    TestSetItemUpdateIn,
    TestSetReportOut,
)
from parsifal.apps.reviews.services import mapping

router = Router(tags=["mapping"])


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
def checklist_get(request, review_id: int, catalog: str = mapping.PETERSEN):
    """
    A checklist with the items applied in this review: ``catalog`` petersen (the default; Petersen et al. 2015 Table
    8) or rapid (rapid reviews only: the collaboration with practitioners and the concessions made to be rapid, each
    concession with the threat it brings; Cartaxo et al. 2020).
    """
    return mapping.checklist(get_review(request, review_id), catalog)


@router.put("/reviews/{int:review_id}/checklist/{key}", response=ChecklistOut, operation_id="checklist_set")
def checklist_set(request, review_id: int, key: str, payload: ChecklistItemIn):
    """Mark an item of a checklist (its key says which) as applied or not; ``notes``: a concession's justification."""
    review = get_review(request, review_id)
    return mapping.set_checklist_item(review=review, key=key, applied=payload.applied, notes=payload.notes)
