"""Reporting: the threats to validity of a review and the manuscripts written from it, with their versions."""

from django.http import FileResponse

from ninja import File, Form, Router
from ninja.files import UploadedFile

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.reporting import (
    ManuscriptIn,
    ManuscriptOut,
    ManuscriptUpdateIn,
    ManuscriptVersionOut,
    ThreatIn,
    ThreatOut,
    ThreatTypesOut,
    ThreatUpdateIn,
)
from parsifal.apps.reviews.services import manuscripts, threats

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


# ---------------------------------------------------------------------------------------------------------------------
# Manuscripts and their versions
# ---------------------------------------------------------------------------------------------------------------------


@router.get("/reviews/{int:review_id}/manuscripts", response=list[ManuscriptOut], operation_id="manuscripts_list")
def manuscripts_list(request, review_id: int):
    """The manuscripts written from the review, each with its versions (the newest first)."""
    return manuscripts.list_manuscripts(get_review(request, review_id))


@router.post("/reviews/{int:review_id}/manuscripts", response={201: ManuscriptOut}, operation_id="manuscripts_create")
def manuscripts_create(request, review_id: int, payload: ManuscriptIn):
    """
    A manuscript: its ``name`` (any: "Full paper", "Extended abstract", "Paper in the IEEE template"...) and what sets
    it apart (``description``). Its files are uploaded as versions.
    """
    review = get_review(request, review_id)
    return 201, manuscripts.add_manuscript(review=review, actor=request.auth, **payload.dict())


@router.patch(
    "/reviews/{int:review_id}/manuscripts/{int:manuscript_id}",
    response=ManuscriptOut,
    operation_id="manuscripts_update",
)
def manuscripts_update(request, review_id: int, manuscript_id: int, payload: ManuscriptUpdateIn):
    review = get_review(request, review_id)
    return manuscripts.update_manuscript(
        review=review, manuscript_id=manuscript_id, **payload.dict(exclude_unset=True)
    )


@router.delete(
    "/reviews/{int:review_id}/manuscripts/{int:manuscript_id}",
    response={204: None},
    operation_id="manuscripts_delete",
)
def manuscripts_delete(request, review_id: int, manuscript_id: int):
    """Delete the manuscript with every version of it (their files too)."""
    manuscripts.remove_manuscript(review=get_review(request, review_id), manuscript_id=manuscript_id)
    return 204, None


@router.post(
    "/reviews/{int:review_id}/manuscripts/{int:manuscript_id}/versions",
    response={201: ManuscriptVersionOut},
    operation_id="manuscripts_versions_upload",
)
def manuscripts_versions_upload(
    request, review_id: int, manuscript_id: int, file: File[UploadedFile], notes: Form[str] = ""
):
    """
    Upload a new version of the manuscript (multipart form: ``file``, and ``notes``: what changed in it). A PDF, a
    Word (.docx) or OpenDocument (.odt) text, a LaTeX source (.tex) or a ZIP, up to PARSIFAL_PDF_MAX_MB; the earlier
    versions stay.
    """
    review = get_review(request, review_id)
    return 201, manuscripts.add_version(
        review=review, manuscript_id=manuscript_id, file=file, notes=notes, actor=request.auth
    )


@router.get(
    "/reviews/{int:review_id}/manuscripts/{int:manuscript_id}/versions/{int:version_id}/file",
    operation_id="manuscripts_versions_download",
)
def manuscripts_versions_download(request, review_id: int, manuscript_id: int, version_id: int):
    """The version's file, with the name it was uploaded with."""
    version = manuscripts.get_version(get_review(request, review_id), version_id, manuscript_id)
    return FileResponse(
        version.file.open(), content_type=version.file.content_type, as_attachment=True, filename=version.file.filename
    )


@router.delete(
    "/reviews/{int:review_id}/manuscripts/{int:manuscript_id}/versions/{int:version_id}",
    response={204: None},
    operation_id="manuscripts_versions_delete",
)
def manuscripts_versions_delete(request, review_id: int, manuscript_id: int, version_id: int):
    """Delete one version and its file; the others keep their numbers."""
    manuscripts.remove_version(
        review=get_review(request, review_id), version_id=version_id, manuscript_id=manuscript_id
    )
    return 204, None
