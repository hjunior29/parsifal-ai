from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse as r

from parsifal.apps.core.exceptions import DomainError
from parsifal.apps.reviews.decorators import author_required
from parsifal.apps.reviews.models import Review
from parsifal.apps.reviews.reporting.export import export_review_to_docx
from parsifal.apps.reviews.services import threats


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
