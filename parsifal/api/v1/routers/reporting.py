"""Reporting: the threats to validity of a review."""

from ninja import Router

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.reporting import ThreatIn, ThreatOut, ThreatTypesOut, ThreatUpdateIn
from parsifal.apps.reviews.services import threats

router = Router(tags=["reporting"])


# ---------------------------------------------------------------------------------------------------------------------
# Threats to validity
# ---------------------------------------------------------------------------------------------------------------------


@router.get("/threats/types", response=ThreatTypesOut, operation_id="threat_types")
def threat_types(request):
    """
    The types suggested for a threat (Petersen et al. 2015 §3.6; Wohlin et al. 2012) and examples of threats to a
    secondary study (Petersen et al. 2015 §5.1.5). A threat may have any other type.
    """
    return {
        "types": list(threats.SUGGESTED_TYPES),
        "examples": [{"title": title, "category": category} for title, category in threats.EXAMPLES],
    }


@router.get("/reviews/{int:review_id}/threats", response=list[ThreatOut], operation_id="threats_list")
def threats_list(request, review_id: int):
    """The review's threats to validity, in their order."""
    return threats.list_threats(get_review(request, review_id))


@router.post("/reviews/{int:review_id}/threats", response={201: ThreatOut}, operation_id="threats_create")
def threats_create(request, review_id: int, payload: ThreatIn):
    """A threat: its name (``title``), type (``category``, free), description and how it was mitigated."""
    return 201, threats.add_threat(review=get_review(request, review_id), **payload.dict())


@router.patch("/reviews/{int:review_id}/threats/{int:threat_id}", response=ThreatOut, operation_id="threats_update")
def threats_update(request, review_id: int, threat_id: int, payload: ThreatUpdateIn):
    review = get_review(request, review_id)
    return threats.update_threat(review=review, threat_id=threat_id, **payload.dict(exclude_unset=True))


@router.delete("/reviews/{int:review_id}/threats/{int:threat_id}", response={204: None}, operation_id="threats_delete")
def threats_delete(request, review_id: int, threat_id: int):
    threats.remove_threat(review=get_review(request, review_id), threat_id=threat_id)
    return 204, None
