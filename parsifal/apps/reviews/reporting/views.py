from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse as r
from django.views.decorators.clickjacking import xframe_options_sameorigin

from parsifal.apps.core.exceptions import DomainError
from parsifal.apps.core.models import files_are_local, files_storage
from parsifal.apps.reviews.decorators import author_required
from parsifal.apps.reviews.models import ManuscriptVersion, Review
from parsifal.apps.reviews.reporting.export import export_review_to_docx
from parsifal.apps.reviews.services import manuscripts, threats


@author_required
@login_required
def reporting(request, username, review_name):
    return redirect(r("threats_to_validity", args=(username, review_name)))


@author_required
@login_required
def export(request, username, review_name):
    review = get_object_or_404(Review, name=review_name, author__username__iexact=username)
    return render(request, "reporting/export.html", {"review": review})


@author_required
@login_required
def download_docx(request):
    review_id = request.GET.get("review-id")
    review = get_object_or_404(Review, pk=review_id)
    sections = request.GET.getlist("export")
    document = export_review_to_docx(review, sections)
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    response["Content-Disposition"] = "attachment; filename={0}.docx".format(review.name)
    document.save(response)
    return response


def _threat_fields(request):
    return {field: request.POST.get(field, "") for field in threats.FIELDS}


@author_required
@login_required
def threats_to_validity(request, username, review_name):
    """
    Threats to Validity: each threat of the review, of a type, with its description and its mitigation; added,
    edited (``?edit=<id>``) and removed here.
    """
    review = request.review
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add":
                threats.add_threat(review=review, **_threat_fields(request))
                messages.success(request, "The threat was added.")
            elif action == "update":
                threats.update_threat(
                    review=review, threat_id=request.POST.get("threat-id"), **_threat_fields(request)
                )
                messages.success(request, "The threat was saved.")
            elif action == "remove":
                threats.remove_threat(review=review, threat_id=request.POST.get("threat-id"))
                messages.success(request, "The threat was removed.")
        except DomainError as error:
            messages.error(request, str(error))
        return redirect("threats_to_validity", review.author.username, review.name)
    groups = threats.grouped(review)
    used = [category for category, _threats in groups if category]
    context = {
        "review": review,
        "groups": groups,
        "count": sum(len(items) for _category, items in groups),
        "types": used + [category for category in threats.SUGGESTED_TYPES if category not in used],
        "examples": threats.EXAMPLES,
        "editing": request.GET.get("edit", ""),
    }
    return render(request, "reporting/threats.html", context)


def _manuscript_action(request, review, action):
    """Does what the form of the Manuscripts page asks; returns its message."""
    if action == "add":
        manuscripts.add_manuscript(
            review=review,
            name=request.POST.get("name", ""),
            description=request.POST.get("description", ""),
            actor=request.user,
        )
        return "The manuscript was added. Upload its first version."
    if action == "update":
        manuscripts.update_manuscript(
            review=review,
            manuscript_id=request.POST.get("manuscript-id"),
            name=request.POST.get("name", ""),
            description=request.POST.get("description", ""),
        )
        return "The manuscript was saved."
    if action == "remove":
        manuscripts.remove_manuscript(review=review, manuscript_id=request.POST.get("manuscript-id"))
        return "The manuscript and its versions were deleted."
    if action == "upload":
        upload = request.FILES.get("file")
        if upload is None:
            raise DomainError("Choose the file of the new version.")
        version = manuscripts.add_version(
            review=review,
            manuscript_id=request.POST.get("manuscript-id"),
            file=upload,
            notes=request.POST.get("notes", ""),
            actor=request.user,
        )
        return f"Version {version.number} was uploaded."
    if action == "remove-version":
        manuscripts.remove_version(review=review, version_id=request.POST.get("version-id"))
        return "The version was deleted."
    raise DomainError("Unknown action.")


@author_required
@login_required
def manuscripts_page(request, username, review_name):
    """
    Manuscripts: the texts written from the review (any name: the paper, a short or an extended version, the same
    paper in another template), each with its versions, the newest first; each upload is a new version.
    """
    review = request.review
    if request.method == "POST":
        try:
            messages.success(request, _manuscript_action(request, review, request.POST.get("action")))
        except DomainError as error:
            messages.error(request, str(error))
        return redirect("manuscripts", review.author.username, review.name)
    items = list(manuscripts.list_manuscripts(review))
    used = {manuscript.name for manuscript in items}
    context = {
        "review": review,
        "manuscripts": items,
        "names": [name for name in manuscripts.SUGGESTED_NAMES if name not in used],
        "editing": request.GET.get("edit", ""),
        "max_mb": manuscripts.max_size_mb(),
        "accept": manuscripts.accepted_extensions(),
    }
    return render(request, "reporting/manuscripts.html", context)


@login_required
@xframe_options_sameorigin
def manuscript_file(request, version_id):
    """
    A version's file: a PDF for the browser to show (the viewer of the Manuscripts page frames it), any other file,
    or a PDF with ``download``, to be saved. Kept in a bucket, the browser is sent to a link of it that expires.
    """
    version = get_object_or_404(ManuscriptVersion.objects.select_related("manuscript__review", "file"), pk=version_id)
    if not version.manuscript.review.is_author_or_coauthor(request.user):
        raise Http404
    if not files_are_local():
        return redirect(files_storage().url(version.file.key))
    attachment = "download" in request.GET or not version.is_pdf
    return FileResponse(
        version.file.open(),
        content_type=version.file.content_type,
        as_attachment=attachment,
        filename=version.file.filename,
    )
