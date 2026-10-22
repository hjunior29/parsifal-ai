import logging
import os
from collections import Counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.context_processors import csrf
from django.template.loader import render_to_string
from django.urls import reverse as r
from django.utils.html import escape
from django.utils.translation import gettext as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

import xlwt

from parsifal.apps.accounts import services as integrations
from parsifal.apps.accounts.forms import model_label
from parsifal.apps.core import library_proxy
from parsifal.apps.core.exceptions import DomainError
from parsifal.apps.core.models import files_are_local, files_storage
from parsifal.apps.reviews.decorators import author_required
from parsifal.apps.reviews.models import (
    Article,
    DataExtractionField,
    Review,
    SearchSession,
    SelectionCriteria,
    Source,
    StudyDecision,
)
from parsifal.apps.reviews.services import (
    ai_runs,
    ai_screening as ai_screening_service,
    analytics,
    decisions,
    extraction,
    full_texts,
    quality,
    reports,
    screening_requests,
    studies,
)

logger = logging.getLogger(__name__)


@author_required
@login_required
def conducting(request, username, review_name):
    return redirect(r("search_studies", args=(username, review_name)))


@author_required
@login_required
def search_studies(request, username, review_name):
    review = get_object_or_404(Review, name=review_name, author__username__iexact=username)
    sessions = review.get_latest_source_search_strings()
    add_sources = review.sources.exclude(id__in=sessions.values("source__id"))
    return render(
        request,
        "conducting/conducting_search_studies.html",
        {"review": review, "add_sources": add_sources},
    )


@author_required
@login_required
@require_POST
def save_source_string(request):
    try:
        review_id = request.POST.get("review-id")
        source_id = request.POST.get("source-id")
        review = Review.objects.get(pk=review_id)
        source = Source.objects.get(pk=source_id)
        search_string = request.POST.get("search_string")
        try:
            search_session = review.get_latest_source_search_strings().get(source=source)
        except SearchSession.DoesNotExist:
            search_session = SearchSession(review=review, source=source)
        search_session.search_string = search_string
        search_session.save()
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def remove_source_string(request):
    review_id = request.POST.get("review-id")
    source_id = request.POST.get("source-id")
    review = get_object_or_404(Review, pk=review_id)
    source = get_object_or_404(Source, pk=source_id)
    try:
        search_session = review.get_latest_source_search_strings().get(source=source)
        search_session.delete()
    except SearchSession.DoesNotExist:
        pass
    messages.success(request, "{0} search string removed successfully!".format(source.name))
    return redirect(r("search_studies", args=(review.author.username, review.name)))


@author_required
@login_required
@require_POST
def import_base_string(request):
    try:
        review_id = request.POST.get("review-id")
        source_id = request.POST.get("source-id")
        review = Review.objects.get(pk=review_id)
        source = Source.objects.get(pk=source_id)
        base_search_string = review.get_generic_search_string().search_string
        try:
            search_session = review.get_latest_source_search_strings().get(source=source)
        except SearchSession.DoesNotExist:
            search_session = SearchSession(review=review, source=source)
        search_session.search_string = base_search_string
        search_session.save()
        return HttpResponse(base_search_string)
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
def import_studies(request, username, review_name):
    review = Review.objects.get(name=review_name, author__username__iexact=username)
    sources = []
    for source in review.sources.all():
        sources.append({"source": source, "count": Article.objects.filter(source=source, review=review).count()})
    return render(
        request,
        "conducting/conducting_import_studies.html",
        {"review": review, "sources": sources},
    )


@author_required
@login_required
def study_selection(request, username, review_name):
    review = Review.objects.get(name=review_name, author__username__iexact=username)
    try:
        active_tab = int(request.GET["source"])
    except Exception:
        active_tab = -1

    add_sources = review.sources.count()
    import_articles = review.get_source_articles().count()

    steps_messages = []
    if not add_sources:
        steps_messages.append(
            'Use the <a href="{0}#sources-section">planning tab</a> to add sources to your review.'.format(
                r("protocol", args=(username, review_name))
            )
        )
    if not import_articles:
        steps_messages.append(
            'Import the studies using the <a href="{0}">import studies tab</a>.'.format(
                r("import_studies", args=(username, review_name))
            )
        )

    finished_all_steps = len(steps_messages) == 0

    return render(
        request,
        "conducting/conducting_study_selection.html",
        {
            "review": review,
            "active_tab": active_tab,
            "steps_messages": steps_messages,
            "finished_all_steps": finished_all_steps,
        },
    )


def build_quality_assessment_table(request, review, order):
    selected_studies = (
        review.get_accepted_articles()
        .prefetch_related("qualityassessment_set")
        .annotate(score=Coalesce(Sum("qualityassessment__answer__weight"), Value(0.0)))
        .order_by(order)
    )
    quality_questions = review.get_quality_assessment_questions()
    quality_answers = review.get_quality_assessment_answers()

    csrf_token = csrf(request)["csrf_token"]

    quality_index = {}
    for study in selected_studies:
        quality_index[study.pk] = {}
        for qa in study.qualityassessment_set.all():
            quality_index[study.pk][qa.question_id] = qa.answer_id

    if quality_questions and quality_answers:
        str_table = ""
        for study in selected_studies:
            str_table += """
            <div class="panel panel-default panel-quality-assessment">
              <div class="panel-heading">
                <h3 class="panel-title">{0} <small>({4})</small><span class="badge score pull-right">{1}</span></h3>
              </div>

            <table class="table" id="tbl-quality" article-id="{2}" csrf-token="{3}">
                <tbody>""".format(
                escape(study.title), study.score, study.id, csrf_token, escape(study.year)
            )

            for question in quality_questions:
                str_table += '<tr question-id="{question_id}"><td>{question_description}</td>'.format(
                    question_id=question.pk,
                    question_description=escape(question.description),
                )

                question_answer_id = quality_index[study.pk].get(question.pk)

                for answer in quality_answers:
                    selected_answer = ""
                    if answer.id == question_answer_id:
                        selected_answer = " selected-answer"
                    str_table += (
                        '<td class="answer {selected}" answer-id="{answer_id}">{answer_description}</td>'.format(
                            selected=selected_answer,
                            answer_id=answer.pk,
                            answer_description=escape(answer.description),
                        )
                    )
                str_table += "</tr>"

            str_table += "</tbody></table></div>"
        return str_table
    else:
        return ""


@author_required
@login_required
def quality_assessment(request, username, review_name):
    review = Review.objects.get(name=review_name, author__username__iexact=username)

    add_sources = review.sources.count()
    import_articles = review.get_source_articles().count()
    select_articles = review.get_accepted_articles().count()
    create_questions = review.get_quality_assessment_questions().count()
    create_answers = review.get_quality_assessment_answers().count()

    steps_messages = []

    if not add_sources:
        steps_messages.append(
            'Use the <a href="/'
            + username
            + "/"
            + review_name
            + '/planning/protocol/#sources-section">planning tab</a> to add sources to your review.'
        )
    if not import_articles:
        steps_messages.append(
            'Import the studies using the <a href="/'
            + username
            + "/"
            + review_name
            + '/conducting/import/">import studies tab</a>.'
        )
    if not select_articles:
        steps_messages.append(
            'Classify the imported studies using the <a href="/'
            + username
            + "/"
            + review_name
            + '/conducting/studies/">study selection tab</a>.'
        )
    if not create_questions:
        steps_messages.append(
            'Create quality assessment questions using the <a href="/'
            + username
            + "/"
            + review_name
            + '/planning/quality/#questions">planning tab</a>.'
        )
    if not create_answers:
        steps_messages.append(
            'Create quality assessment answers using the <a href="/'
            + username
            + "/"
            + review_name
            + '/planning/quality/#answers">planning tab</a>.'
        )

    finished_all_steps = len(steps_messages) == 0

    order = "title"
    if "order" in request.GET:
        order = request.GET.get("order")
    elif "quality_assessment_order" in request.session:
        order = request.session.get("quality_assessment_order")
    if order not in ("title", "-title", "year", "-year"):
        order = "title"
    request.session["quality_assessment_order"] = order

    quality_assessment_table = build_quality_assessment_table(request, review, order)

    return render(
        request,
        "conducting/conducting_quality_assessment.html",
        {
            "review": review,
            "steps_messages": steps_messages,
            "quality_assessment_table": quality_assessment_table,
            "finished_all_steps": finished_all_steps,
            "order": order,
        },
    )


def build_data_extraction_field_row(article, field):
    str_field = ""

    extraction = None
    for data_extraction in article.dataextraction_set.all():
        if data_extraction.field_id == field.pk:
            extraction = data_extraction
            break

    if field.field_type == DataExtractionField.BOOLEAN_FIELD:
        true = ""
        false = ""
        if extraction is not None:
            if extraction.get_value():
                true = " selected"
            else:
                false = " selected"

        str_field = """<select name="value" class="form-control">
            <option value="">Select...</option>
            <option value="True"{0}>True</option>
            <option value="False"{1}>False</option>
          </select>""".format(
            true, false
        )

    elif field.field_type == DataExtractionField.DATE_FIELD:
        if extraction is not None:
            value = extraction.get_date_value_as_string()
        else:
            value = ""
        str_field = '<input type="text" class="form-control" name="{0}-{1}-value" maxlength="10" value="{2}">'.format(
            article.id, field.id, escape(value)
        )

    elif field.field_type == DataExtractionField.SELECT_ONE_FIELD:
        str_field = """<select name="{0}-{1}-value" class="form-control">
            <option value="">Select...</option>""".format(
            article.id, field.id
        )
        for value in field.dataextractionlookup_set.all():
            if extraction is not None and extraction.get_value() is not None and extraction.get_value().id == value.id:
                selected = " selected"
            else:
                selected = ""
            str_field += """<option value="{0}"{1}>{2}</option>""".format(value.id, selected, escape(value.value))
        str_field += "</select>"

    elif field.field_type == DataExtractionField.SELECT_MANY_FIELD:
        for value in field.dataextractionlookup_set.all():
            if extraction is not None and value in extraction.get_value():
                checked = " checked"
            else:
                checked = ""
            str_field += (
                '<label class="checkbox-inline">'
                '<input type="checkbox" name="{0}-{1}-value" value="{2}"{3}>{4}'
                "</label> ".format(article.id, field.id, value.id, checked, escape(value.value))
            )

    elif field.field_type == DataExtractionField.STRING_FIELD:
        value = ""
        if extraction is not None:
            value = extraction.get_value()
        str_field = '<textarea class="form-control" name="{0}-{1}-value" rows="3">{2}</textarea>'.format(
            article.id, field.id, escape(value)
        )
    else:
        value = ""
        if extraction is not None:
            value = extraction.get_value()
        str_field = '<input type="text" class="form-control" maxlength="30" name="{0}-{1}-value" value="{2}">'.format(
            article.id, field.id, escape(value)
        )

    return str_field


def build_data_extraction_table(review, is_finished):
    selected_studies = review.get_final_selection_articles().prefetch_related(
        "dataextraction_set__field",
        "dataextraction_set__select_values",
    )
    if is_finished is not None:
        selected_studies = selected_studies.filter(finished_data_extraction=is_finished)
    data_extraction_fields = review.get_data_extraction_fields().prefetch_related("dataextractionlookup_set")
    has_quality_assessment = review.has_quality_assessment_checklist()
    if selected_studies and data_extraction_fields:
        str_table = '<div class="panel-group">'
        for study in selected_studies:
            if has_quality_assessment:
                str_table += """<div class="panel panel-default data-extraction-panel">
                  <div class="panel-heading">
                    <h3 class="panel-title">{0}
                      <span class="badge">{1}</span>""".format(
                    escape(study.title), study.score
                )

                if study.finished_data_extraction:
                    str_table += '<span class="pull-right"><a href="javascript:void(0);" class="js-finished-button js-mark-as-not-finished"><span class="glyphicon glyphicon-check"></span> <span class="action-text">mark as undone</span></a></span>'  # noqa
                else:
                    str_table += '<span class="pull-right"><a href="javascript:void(0);" class="js-finished-button js-mark-as-finished"><span class="glyphicon glyphicon-unchecked"></span> <span class="action-text">mark as done</span></a></span>'  # noqa

                str_table += "</h3></div>"
                str_table += '<div class="panel-body form-horizontal" data-article-id="{0}">'.format(study.id)
            else:
                str_table += """<div class="panel panel-default data-extraction-panel">
                  <div class="panel-heading">
                    <h3 class="panel-title">{1}</h3>
                  </div>
                  <div class="panel-body form-horizontal" data-article-id="{0}">""".format(
                    study.id, escape(study.title)
                )
            for field in data_extraction_fields:
                str_table += """<div class="form-group" data-field-id="{0}">
                    <label class="control-label col-md-2">{1}</label>
                    <div class="col-md-10">{2}<span class="help-block error" style="display: none;"></span>
                    </div>
                </div>
                """.format(
                    field.id, escape(field.description), build_data_extraction_field_row(study, field)
                )
            str_table += "</div></div>"
        str_table += "</div>"
        return str_table
    else:
        return ""


@author_required
@login_required
def data_extraction(request, username, review_name):
    review = Review.objects.get(name=review_name, author__username__iexact=username)

    add_sources = review.sources.count()
    import_articles = review.get_source_articles().count()
    select_articles = review.get_accepted_articles().count()
    create_fields = review.get_data_extraction_fields().count()

    steps_messages = []

    if not add_sources:
        steps_messages.append(
            'Use the <a href="/'
            + username
            + "/"
            + review_name
            + '/planning/protocol/#sources-section">planning tab</a> to add sources to your review.'
        )
    if not import_articles:
        steps_messages.append(
            'Import the studies using the <a href="/'
            + username
            + "/"
            + review_name
            + '/conducting/import/">import studies tab</a>.'
        )
    if not select_articles:
        steps_messages.append(
            'Classify the imported studies using the <a href="/'
            + username
            + "/"
            + review_name
            + '/conducting/studies/">study selection tab</a>.'
        )
    if not create_fields:
        steps_messages.append(
            'Create data extraction fields using the <a href="/'
            + username
            + "/"
            + review_name
            + '/planning/extraction/">planning tab</a>.'
        )

    finished_all_steps = not steps_messages

    tab = request.GET.get("tab", "todo")
    if tab not in ["todo", "done", "all"]:
        tab = "todo"

    is_finished = None

    if tab == "todo":
        is_finished = False
    elif tab == "done":
        is_finished = True
    elif tab == "all":
        is_finished = None

    try:
        data_extraction_table = build_data_extraction_table(review, is_finished)
    except Exception:
        logger.exception("An error occurred while trying to build data extraction table.")
        data_extraction_table = "<h3>Something went wrong while rendering the data extraction form.</h3>"

    return render(
        request,
        "conducting/conducting_data_extraction.html",
        {
            "review": review,
            "steps_messages": steps_messages,
            "data_extraction_table": data_extraction_table,
            "finished_all_steps": finished_all_steps,
            "tab": tab,
        },
    )


def _import_articles(request, review, source, content):
    try:
        result = studies.import_bibtex(review=review, source_id=source.pk, content=content, actor=request.user)
    except DomainError as error:
        messages.error(request, _("An error occurred while trying to parse the bibtex file. Error detail: %s") % error)
        return
    if result.imported > 0:
        messages.success(request, "{0} articles successfully imported to {1}!".format(result.imported, source.name))
    if result.failed > 0:
        messages.warning(
            request,
            "{0} articles could not be imported because of invalid format or invalid utf-8 string.".format(
                result.failed
            ),
        )
    for warning in result.warnings:
        if "could not be read" in warning or "key contains spaces" in warning:
            messages.warning(request, warning)
    if result.imported == 0 and result.failed == 0:
        messages.warning(request, "The bibtex file had no valid entry!")


@author_required
@login_required
@require_POST
def import_bibtex(request):
    review_id = request.POST["review-id"]
    source_id = request.POST["source-id"]

    review = Review.objects.get(pk=review_id)
    source = Source.objects.get(pk=source_id)

    bibtex_file = request.FILES["bibtex"]

    ext = os.path.splitext(bibtex_file.name)[1]
    valid_extensions = [".bib", ".bibtex"]

    if ext in valid_extensions or bibtex_file.content_type == "application/x-bibtex":
        _import_articles(request, review, source, bibtex_file.read())
    else:
        messages.error(request, _("Invalid file type. Only .bib or .bibtex files are accepted."))

    return redirect(r("import_studies", args=(review.author.username, review.name)))


@author_required
@login_required
@require_POST
def import_bibtex_raw_content(request):
    review_id = request.POST.get("review-id")
    source_id = request.POST.get("source-id")
    bibtex_file = request.POST.get("bibtex_file")

    review = Review.objects.get(pk=review_id)
    source = Source.objects.get(pk=source_id)

    _import_articles(request, review, source, bibtex_file or "")

    return redirect(r("import_studies", args=(review.author.username, review.name)))


@author_required
@login_required
@require_POST
def clear_source_articles(request):
    review = get_object_or_404(Review, pk=request.POST["review-id"])
    try:
        count = studies.clear_articles(review=review, source_id=request.POST.get("source-id"))
    except DomainError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, _("%(count)s studies deleted.") % {"count": count})
    return redirect(r("import_studies", args=(review.author.username, review.name)))


@author_required
@login_required
def source_articles(request):
    review_id = request.GET["review-id"]
    source_id = request.GET["source-id"]

    review = Review.objects.get(pk=review_id)
    if source_id != "None":
        articles = review.get_source_articles(source_id)
        source = Source.objects.get(pk=source_id)
    else:
        articles = review.get_source_articles()
        source = Source()
    articles = ai_screening_service.with_relevance(articles)  # the AI column: the latest answer about each study

    return render(
        request,
        "conducting/partial_conducting_articles.html",
        {
            "review": review,
            "source": source,
            "articles": articles,
            "starred_count": articles.filter(starred_at__isnull=False).count(),
        },
    )


@author_required
@login_required
def article_details(request):
    review_id = request.GET["review-id"]
    article_id = request.GET["article-id"]

    review = get_object_or_404(Review, pk=review_id)
    article = get_object_or_404(
        Article.objects.select_related("pdf__uploaded_by", "starred_by__profile"), pk=article_id, review_id=review_id
    )

    context = {"review": review, "article": article, "pdf_max_mb": full_texts.max_size_mb()}
    # Via CAPES: the study through the user's library proxy (Settings → Library access).
    proxy = integrations.library_proxy_address(request.user)
    context.update(access_url=article.access_url(proxy), access_label=library_proxy.label(proxy) if proxy else "")
    context.update(_decisions_context(request, review, article))
    return render(request, "conducting/partial_conducting_article_details.html", context)


def _article_pdf_tab(request, review, article_id, message=None):
    article = get_object_or_404(Article.objects.select_related("pdf__uploaded_by"), pk=article_id, review=review)
    context = {"review": review, "article": article, "pdf_max_mb": full_texts.max_size_mb(), "pdf_message": message}
    return render(request, "conducting/partial_conducting_article_pdf.html", context)


@login_required
@xframe_options_sameorigin
def article_pdf(request, article_id):
    """
    The study's PDF for the browser to show (the Full text tab frames it). Kept on this server, it is sent from
    here; kept in a bucket, the browser is sent to a link of the bucket that expires.
    """
    article = get_object_or_404(Article.objects.select_related("review", "pdf"), pk=article_id)
    if not article.review.is_author_or_coauthor(request.user) or article.pdf is None:
        raise Http404
    if files_are_local():
        return FileResponse(article.pdf.open(), content_type=article.pdf.content_type, filename=article.pdf.filename)
    return redirect(files_storage().url(article.pdf.key))


@author_required
@login_required
@require_POST
def star_article(request):
    """Star (``starred=1``) or unstar (``starred=0``) a study in the review; returns its star."""
    review = get_object_or_404(Review, pk=request.POST.get("review-id"))
    try:
        article = studies.set_starred(
            review=review,
            article_id=request.POST.get("article-id"),
            starred=request.POST.get("starred") == "1",
            actor=request.user,
        )
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    return render(request, "conducting/partial_conducting_article_star.html", {"article": article})


@author_required
@login_required
@require_POST
def upload_article_pdf(request):
    """Attach (or replace) the study's PDF; returns the Full text tab."""
    review = get_object_or_404(Review, pk=request.POST.get("review-id"))
    try:
        upload = request.FILES.get("pdf")
        if upload is None:
            raise DomainError("Choose a PDF to upload.")
        full_texts.attach_pdf(
            review=review, article_id=request.POST.get("article-id"), file=upload, actor=request.user
        )
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    return _article_pdf_tab(request, review, request.POST.get("article-id"), message="The PDF was uploaded.")


@author_required
@login_required
@require_POST
def remove_article_pdf(request):
    """Delete the study's PDF; returns the Full text tab."""
    review = get_object_or_404(Review, pk=request.POST.get("review-id"))
    try:
        full_texts.remove_pdf(review=review, article_id=request.POST.get("article-id"))
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    return _article_pdf_tab(request, review, request.POST.get("article-id"), message="The PDF was removed.")


def _decisions_context(request, review, article, message=None):
    rows = list(decisions.article_decisions(review=review, article_id=article.pk))
    mine = next((d for d in rows if d.user_id == request.user.pk), None)
    return {
        "decisions": rows,
        "my_decision": mine,
        "decision_stages": StudyDecision.STAGES,
        "decision_statuses": Article.ARTICLE_STATUS,
        "decision_message": message,
    }


@author_required
@login_required
@require_POST
def record_decision(request):
    """Record the current user's independent decision for an article; returns the Reviewers tab partial."""
    review = get_object_or_404(Review, pk=request.POST.get("review-id"))
    try:
        decision = decisions.record_decision(
            review=review,
            article_id=request.POST.get("article-id"),
            actor=request.user,
            status=request.POST.get("status"),
            stage=request.POST.get("stage") or StudyDecision.TITLE_ABSTRACT,
            criteria_id=request.POST.get("selection_criteria") or None,
            comments=request.POST.get("comments", ""),
        )
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    context = {"review": review, "article": decision.article}
    context.update(_decisions_context(request, review, decision.article, message="Your decision was recorded."))
    return render(request, "conducting/partial_conducting_article_decisions.html", context)


RULE_LABELS = (
    (decisions.RULE_UNANIMOUS, "Unanimous — all reviewers agree"),
    (decisions.RULE_ANY_INCLUDE, "Any include — accepted if any reviewer accepts"),
    (decisions.RULE_MAJORITY, "Majority — strict majority of reviewers"),
)


def _agreement_context(request, review, stage, result=None):
    context = {
        "review": review,
        "stage": stage,
        "stage_label": dict(StudyDecision.STAGES).get(stage, stage),
        "stages": StudyDecision.STAGES,
        "rules": RULE_LABELS,
        "rule_label": dict(RULE_LABELS).get(result["rule"], result["rule"]).split(" — ")[0] if result else None,
        "summary": decisions.summary(review),
        "result": result,
        "selected_rule": result["rule"] if result else None,
        "agreement": None,
        "agreement_error": None,
    }
    try:
        context["disagreements"] = decisions.disagreements(review=review, stage=stage)
        context["agreement"] = decisions.agreement(review=review, stage=stage)
    except DomainError as error:
        context.setdefault("disagreements", [])
        context["agreement_error"] = str(error)
    # Who set the status the disagreeing articles have now: a person who consolidated, or the run of an AI reviewer.
    context["status_set_by"] = Counter(
        row["article"].updated_by.username if row["article"].updated_by else "nobody"
        for row in context["disagreements"]
    ).most_common()
    return context


@author_required
@login_required
def agreement(request):
    """Reviewer agreement panel: summary, Cohen's kappa, disagreements and the consolidation form."""
    review = get_object_or_404(Review, pk=request.GET.get("review-id"))
    stage = request.GET.get("stage") or StudyDecision.TITLE_ABSTRACT
    if stage not in dict(StudyDecision.STAGES):
        return HttpResponseBadRequest("Unknown stage.")
    return render(request, "conducting/partial_conducting_agreement.html", _agreement_context(request, review, stage))


@author_required
@login_required
@require_POST
def consolidate(request):
    """Set Article.status from the reviewers' decisions with the chosen rule; re-renders the agreement panel."""
    review = get_object_or_404(Review, pk=request.POST.get("review-id"))
    stage = request.POST.get("stage") or StudyDecision.TITLE_ABSTRACT
    try:
        result = decisions.consolidate(
            review=review, stage=stage, rule=request.POST.get("rule", decisions.RULE_UNANIMOUS), actor=request.user
        )
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    return render(
        request, "conducting/partial_conducting_agreement.html", _agreement_context(request, review, stage, result)
    )


@author_required
@login_required
def ai_screening(request):
    """
    The setup window of Exclude, Include or Screen with AI (``phase``): every setting of the review's last run of
    that action, Parsifal's defaults with ``defaults`` (Restore defaults), or the settings of the run ``run-id`` to
    run it again.
    """
    review = get_object_or_404(Review, pk=request.GET.get("review-id"))
    restored = bool(request.GET.get("defaults"))
    try:
        like = ai_screening_service.get_run(review, request.GET["run-id"]) if request.GET.get("run-id") else None
        if like is not None:
            settings = {**ai_runs.rerun_settings(review, like), "run": like}
        else:
            phase = ai_screening_service.clean_phase(request.GET.get("phase"))
            settings = ai_screening_service.starting_settings(review, phase, defaults=restored)
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    phase = settings["phase"]
    integration = integrations.get_jev(request.user)
    defaults = ai_screening_service.default_context(review)
    defaults.update({name: value for name, value in (settings["context"] or {}).items() if value is not None})
    agent_ids = ai_screening_service.agent_ids(review)
    reviewers = [
        {"user": member, "is_agent": member.pk in agent_ids, "is_you": member.pk == request.user.pk}
        for member in ai_screening_service.reviewer_choices(review, request.user)
    ]
    selected = settings["reviewer_id"]
    if selected not in {row["user"].pk for row in reviewers}:
        selected = reviewers[0]["user"].pk if len(reviewers) == 1 else None
    selected_model = settings["model"] or (integration.model if integration else "")
    models, models_error = integrations.jev_models(request.user) if integration else ([], "")
    if integration and selected_model not in {model["name"] for model in models}:
        models = [*models, {"name": selected_model, "description": "", "release_date": ""}] if models else []
    unfinished = ai_screening_service.unfinished_run(review)
    # Every criterion of the action, checked when the run sends it; an inclusion criterion with its threshold.
    chosen = set(settings["criteria_ids"])
    thresholds = settings["thresholds"] or {}
    options = [
        dict(
            option,
            checked=option["id"] in chosen,
            threshold=thresholds.get(option["key"], ai_screening_service.DEFAULT_THRESHOLD),
        )
        for option in ai_screening_service.criteria_options(review, phase)
    ]
    threshold, min_threshold, max_threshold = ai_screening_service.threshold_range()
    if settings["threshold"] is not None:
        threshold = settings["threshold"]
    statuses = settings["statuses"] or ai_screening_service.DEFAULT_STATUSES[phase]
    context = {
        "review": review,
        "phase": phase,
        "like": like,
        "from_run": None if like else settings["run"],
        "restored": restored,
        "selected_model": selected_model,
        "selected_source": settings["source_id"] or "",
        "guidance": settings["guidance"],
        "exclusion": phase in (ai_screening_service.EXCLUSION, ai_screening_service.SCREEN),
        "inclusion": phase in (ai_screening_service.INCLUSION, ai_screening_service.SCREEN),
        "screen": phase == ai_screening_service.SCREEN,
        "label": ai_screening_service.LABELS[phase],
        "inclusion_rule": review.get_inclusion_rule_display(),
        "integration": integration,
        "unfinished": unfinished,
        "unfinished_label": ai_screening_service.LABELS[unfinished.phase] if unfinished else "",
        "unfinished_active": unfinished is not None and ai_screening_service.is_active(unfinished),
        "unfinished_progress": ai_screening_service.progress(unfinished) if unfinished else None,
        "reviewers": reviewers,
        "selected_reviewer": selected,
        "models": [{"name": m["name"], "label": model_label(m)} for m in models],
        "models_error": models_error,
        "inclusion_options": [option for option in options if option["key"].startswith("I")],
        "exclusion_options": [option for option in options if option["key"].startswith("E")],
        "context_fields": [
            {"name": name, "label": label, "value": defaults[name], "limit": limit, "multiline": limit > 255}
            for name, label, limit in ai_screening_service.CONTEXT_FIELDS
        ],
        "guidance_length": ai_screening_service.GUIDANCE_LENGTH,
        "threshold": threshold,
        "min_threshold": min_threshold,
        "max_threshold": max_threshold,
        "sources": [
            {"id": "", "name": "All sources"},
            *({"id": s.pk, "name": s.name} for s in review.sources.order_by("name")),
        ],
        "statuses": [
            {"code": code, "label": label, "checked": code in statuses}
            for code, label in ai_screening_service.STATUSES
        ],
        # Studies per source and status: the page adds up the checked statuses of the chosen source.
        "counts": ai_screening_service.scope_counts(review),
        "template": screening_requests.as_text(settings["template"]),
        "placeholders": screening_requests.PLACEHOLDERS,
    }
    try:
        ai_screening_service.clean_criteria(review, phase)
    except DomainError as error:
        context["missing_criteria"] = str(error)
    return render(request, "conducting/partial_conducting_ai_screening.html", context)


def _ai_screening_error(error):
    return JsonResponse({"error": str(error)}, status=400)


def _ai_screening_settings(request):
    """The settings of the window's form shared by a run and its preview."""
    return {
        "phase": request.POST.get("phase"),
        "model": request.POST.get("model"),
        "context": {
            name: request.POST.get(f"context-{name}", "") for name, _, _ in ai_screening_service.CONTEXT_FIELDS
        },
        "guidance": request.POST.get("guidance", ""),
        "template": request.POST.get("template"),
        "source_id": request.POST.get("source-id", ""),  # "": all sources
        "statuses": request.POST.getlist("statuses"),
        # The window marks its criteria checkboxes, so that none checked is not mistaken for none sent.
        "criteria_ids": request.POST.getlist("criteria") if request.POST.get("criteria-sent") else None,
    }


@author_required
@login_required
@require_POST
def ai_screening_start(request):
    review = get_object_or_404(Review, pk=request.POST.get("review-id"))
    try:
        run = ai_screening_service.start_run(
            review=review,
            actor=request.user,
            reviewer_id=request.POST.get("reviewer-id"),
            threshold=request.POST.get("threshold"),
            # Inclusion criteria: one threshold each, in fields named threshold-I1, threshold-I2…
            thresholds={
                name.removeprefix("threshold-"): value
                for name, value in request.POST.items()
                if name.startswith("threshold-")
            },
            **_ai_screening_settings(request),
        )
    except DomainError as error:
        return _ai_screening_error(error)
    return JsonResponse({"run": ai_screening_service.progress(run)})


@author_required
@login_required
@require_POST
def ai_screening_preview(request):
    """What a run with the window's settings would send to Jev about the first study in scope (nothing is sent)."""
    review = get_object_or_404(Review, pk=request.POST.get("review-id"))
    try:
        preview = ai_screening_service.preview(
            review=review,
            actor=request.user,
            article_id=request.POST.get("article-id") or None,
            **_ai_screening_settings(request),
        )
    except DomainError as error:
        return _ai_screening_error(error)
    article = preview["article"]
    return JsonResponse(
        {"article": {"id": article.pk, "title": article.title or article.bibtex_key}, "request": preview["request"]}
    )


@author_required
@login_required
@require_POST
def ai_screening_step(request):
    """Screen the next few studies of the run; the page calls this until the run is no longer running."""
    review = get_object_or_404(Review, pk=request.POST.get("review-id"))
    try:
        run = ai_screening_service.get_run(review, request.POST.get("run-id"))
        results = ai_screening_service.process_step(run=run, actor=request.user)
    except DomainError as error:
        return _ai_screening_error(error)
    return JsonResponse(
        {
            "run": ai_screening_service.progress(run),
            "results": [
                {
                    "title": result.article.title or result.article.bibtex_key,
                    "outcome": result.outcome,
                    "p_exclude": result.p_exclude,
                    "p_include": result.p_include,
                    "criteria": ai_screening_service.criteria_key(run, result.selection_criteria_id),
                    "error": result.error,
                }
                for result in results
            ],
        }
    )


@author_required
@login_required
@require_POST
def ai_screening_impact(request):
    """What a run with the window's settings would rewrite, to confirm before starting it (nothing is started)."""
    review = get_object_or_404(Review, pk=request.POST.get("review-id"))
    try:
        impact = ai_runs.impact(
            review=review,
            actor=request.user,
            reviewer_id=request.POST.get("reviewer-id"),
            phase=request.POST.get("phase"),
            statuses=request.POST.getlist("statuses"),
            source_id=request.POST.get("source-id", ""),
        )
    except DomainError as error:
        return _ai_screening_error(error)
    return JsonResponse(impact)


def _clock(seconds):
    """Seconds as m:ss, or h:mm:ss from an hour on (as the run's window shows its time)."""
    seconds = max(0, round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _run_settings(run, sources):
    """Threshold(s), statuses and source of a run, as the AI runs window lists them."""
    parameters = run.parameters
    if parameters.get("thresholds"):
        thresholds = " · ".join(f"{key} {value:.2f}" for key, value in parameters["thresholds"].items())
    elif parameters.get("threshold") is not None:
        thresholds = f"{parameters['threshold']:.2f}"
    else:
        thresholds = "—"
    names = dict(ai_screening_service.STATUSES)
    statuses = ", ".join(names.get(code, code) for code in parameters.get("statuses", []))
    source = sources.get(parameters.get("source_id"), "All sources") if parameters.get("source_id") else "All sources"
    return {"thresholds": thresholds, "statuses": statuses or "—", "source": source}


def _run_state(run):
    if run.status == run.RUNNING:
        return "Screening now" if ai_screening_service.is_active(run) else "Interrupted"
    return run.get_status_display()


def _run_rows(request, review, runs):
    """The AI runs window's rows for ``runs``: what each is, how it went and whether it can be undone."""
    controls = ai_runs.controls(review, request.user, runs)
    sources = dict(review.sources.values_list("pk", "name"))
    rows = []
    for run in runs:
        progress = ai_screening_service.progress(run)
        finished = run.status == run.FINISHED and run.finished_at
        rows.append(
            {
                "run": run,
                "label": ai_screening_service.LABELS[run.phase],
                "progress": progress,
                "decided": progress["processed"] - progress["failed"],  # the studies that got a decision
                "state": _run_state(run),
                # A discarded run ended when the next one started: only a finished run's time says how long it took.
                "duration": _clock((run.finished_at - run.created_at).total_seconds()) if finished else "",
                **_run_settings(run, sources),
                **controls[run.pk],
            }
        )
    return rows


def _ai_runs_context(request, review, message=None):
    rows = _run_rows(request, review, list(ai_screening_service.list_runs(review)))
    latest = next((row["run"] for row in rows if row["latest"]), None)
    return {"review": review, "rows": rows, "latest": latest, "message": message}


@author_required
@login_required
def ai_runs_window(request):
    """The AI runs window: every Exclude, Include and Retain with AI run, how much of it stands, run again, undo."""
    review = get_object_or_404(Review, pk=request.GET.get("review-id"))
    return render(request, "conducting/partial_conducting_ai_runs.html", _ai_runs_context(request, review))


# How a result reads in the run's details, by phase and outcome.
OUTCOME_LABELS = {
    ai_screening_service.EXCLUSION: {"excluded": "Rejected", "passed": "Passed"},
    ai_screening_service.INCLUSION: {"included": "Accepted", "undecided": "Undecided"},
    ai_screening_service.SCREEN: {"excluded": "Rejected", "included": "Accepted", "undecided": "Undecided"},
    ai_screening_service.RETENTION: {"included": "Retained", "excluded": "Not retained"},
}


@author_required
@login_required
def ai_run(request):
    """One run in the AI runs window: its settings and what Jev answered for each study."""
    review = get_object_or_404(Review, pk=request.GET.get("review-id"))
    try:
        run = ai_screening_service.get_run(review, request.GET.get("run-id"))
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    standing = set(run.decisions.values_list("article_id", flat=True))
    statuses = dict(Article.ARTICLE_STATUS)
    labels = OUTCOME_LABELS[run.phase]
    results = []
    for result in ai_screening_service.list_results(run):
        if run.phase in (ai_screening_service.EXCLUSION, ai_screening_service.SCREEN):
            probability = result.p_exclude
        else:
            probability = result.p_include
        details = []
        if result.outcome == "excluded" and run.phase != ai_screening_service.RETENTION:
            details.append(ai_screening_service.criteria_key(run, result.selection_criteria_id) or "")
        if run.phase in (ai_screening_service.INCLUSION, ai_screening_service.SCREEN) and result.probabilities:
            details += [f"{key} {value:.2f}" for key, value in result.probabilities.items() if key.startswith("I")]
        detail = " · ".join(part for part in details if part)
        results.append(
            {
                "result": result,
                "title": result.article.title or result.article.bibtex_key,
                "previous": statuses.get(result.previous_status, ""),
                "outcome": labels.get(result.outcome) or result.get_outcome_display(),
                "probability": probability,
                "detail": detail,
                "standing": result.article_id in standing,
            }
        )
    context = {
        "review": review,
        "row": _run_rows(request, review, [run])[0],
        "parameters": run.parameters,
        "template": screening_requests.as_text(run.parameters["template"]) if run.parameters.get("template") else "",
        "context_fields": [
            (label, run.parameters.get("context", {}).get(name, ""))
            for name, label, _limit in ai_screening_service.CONTEXT_FIELDS
        ],
        "results": results,
        "outcomes": sorted({row["outcome"] for row in results}),
    }
    return render(request, "conducting/partial_conducting_ai_run.html", context)


@author_required
@login_required
def ai_run_undo(request):
    """
    Undo a run: GET shows what undoing it would do, POST does it and returns the list of runs with what was done.
    """
    data = request.POST if request.method == "POST" else request.GET
    review = get_object_or_404(Review, pk=data.get("review-id"))
    try:
        if request.method != "POST":
            summary = ai_runs.undo_preview(review=review, actor=request.user, run_id=data.get("run-id"))
            run = ai_screening_service.get_run(review, summary["run_id"])
            context = {
                "review": review,
                "run": run,
                "label": ai_screening_service.LABELS[run.phase],
                "summary": summary,
                # The run that becomes the latest once this one is undone.
                "previous": review.screening_runs.exclude(pk=run.pk).order_by("-created_at", "-pk").first(),
                "back_to": [
                    (label, summary["back_to"][code])
                    for code, label in Article.ARTICLE_STATUS
                    if code in summary["back_to"]
                ],
            }
            return render(request, "conducting/partial_conducting_ai_run_undo.html", context)
        summary = ai_runs.undo_run(review=review, actor=request.user, run_id=data.get("run-id"))
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    context = _ai_runs_context(request, review, message=summary["message"])
    return render(request, "conducting/partial_conducting_ai_runs.html", context)


"""
@author_required
@login_required
def articles_upload(request):
    if request.method == 'POST':
        form = ArticleUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES['article_file']
            review_id = request.POST.get('review-id')
            review = Review.objects.get(pk=review_id)

            article_id = request.POST.get('article-id')
            article = Article.objects.get(pk=article_id)

            article_file = ArticleFile(review=review,
                    article=article,
                    user=request.user,
                    article_file=uploaded_file,
                    name=uploaded_file.name,
                    size=uploaded_file.size)
            article_file.save()

            results = [ { 'name': article_file.name, 'size': article_file.size } ]

            return HttpResponse(json.dumps(results), content_type='application/json')
        else:
            return HttpResponseBadRequest()
    else:
        return HttpResponseBadRequest()
"""


def build_article_table_row(article):
    """The study's row in the study list, as the list renders it (after a save, it replaces the old one)."""
    return render_to_string("conducting/partial_conducting_article_row.html", {"article": article})


@author_required
@login_required
def save_article_details(request):
    if request.method == "POST":
        try:
            article_id = request.POST["article-id"]
            review_id = request.POST["review-id"]

            if article_id != "None":
                article = get_object_or_404(Article, pk=article_id, review_id=review_id)
            else:
                source_id = request.POST["source-id"]
                review = get_object_or_404(Review, pk=review_id)
                source = get_object_or_404(Source, pk=source_id)
                article = Article(review=review, source=source)

            article.bibtex_key = request.POST["bibtex-key"][:100]
            article.title = request.POST["title"][:1000]
            article.author = request.POST["author"][:1000]
            article.journal = request.POST["journal"][:1000]
            article.year = request.POST["year"][:10]
            article.pages = request.POST["pages"][:20]
            article.volume = request.POST["volume"][:100]
            article.author = request.POST["author"][:1000]
            article.abstract = request.POST["abstract"][:4000]
            article.document_type = request.POST["document-type"][:100]
            article.doi = request.POST["doi"][:50]
            article.url = request.POST["url"][:500]
            article.affiliation = request.POST["affiliation"][:500]
            article.author_keywords = request.POST["author_keywords"][:500]
            article.keywords = request.POST["keywords"][:500]
            article.publisher = request.POST["publisher"][:100]
            article.issn = request.POST["issn"][:50]
            article.language = request.POST["language"][:50]
            article.note = request.POST["note"][:500]

            article.comments = request.POST["comments"][:4000]
            status = request.POST["status"][:1]
            if status in (Article.UNCLASSIFIED, Article.REJECTED, Article.ACCEPTED, Article.DUPLICATED):
                article.status = status

            selection_criteria_id = request.POST.get("selection_criteria")
            try:
                selection_criteria = SelectionCriteria.objects.get(pk=selection_criteria_id)
                article.selection_criteria = selection_criteria
            except Exception:
                article.selection_criteria = None

            article.updated_by = request.user
            article.save()

            return HttpResponse(build_article_table_row(article))
        except Exception:
            return HttpResponseBadRequest()
    else:
        return HttpResponseBadRequest()


@author_required
@login_required
def save_quality_assessment(request):
    try:
        review = get_object_or_404(Review, pk=request.POST["review-id"])
        assessment = quality.assess(
            review=review,
            article_id=request.POST["article-id"],
            question_id=request.POST["question-id"],
            answer_id=request.POST["answer-id"],
            actor=request.user,
        )
        return HttpResponse(assessment.article.get_score())
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    except KeyError:
        return HttpResponseBadRequest()


@author_required
@login_required
def quality_assessment_detailed(request):
    try:
        review_id = request.GET["review-id"]
        review = Review.objects.get(pk=review_id)
        order = request.session.get("quality_assessment_order", "title")
        quality_assessment_table = build_quality_assessment_table(request, review, order)
        return render(
            request,
            "conducting/partial_conducting_quality_assessment_detailed.html",
            {"review": review, "quality_assessment_table": quality_assessment_table, "order": order},
        )
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
def quality_assessment_summary(request):
    try:
        review_id = request.GET["review-id"]
        review = Review.objects.get(pk=review_id)
        return render(
            request,
            "conducting/partial_conducting_quality_assessment_summary.html",
            {"review": review},
        )
    except Exception:
        return HttpResponseBadRequest()


def _multiple_articles_action(request, status=None):
    try:
        review = get_object_or_404(Review, pk=request.POST["review-id"])
        article_ids = [pk for pk in request.POST["article_ids"].split("|") if pk]
        if article_ids:
            if status is None:
                studies.delete_articles(review=review, article_ids=article_ids)
            else:
                studies.set_status(review=review, article_ids=article_ids, status=status, actor=request.user)
        return HttpResponse()
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    except KeyError:
        return HttpResponseBadRequest()


@author_required
@login_required
def multiple_articles_action_remove(request):
    return _multiple_articles_action(request)


@author_required
@login_required
def multiple_articles_action_unclassify(request):
    return _multiple_articles_action(request, Article.UNCLASSIFIED)


@author_required
@login_required
def multiple_articles_action_accept(request):
    return _multiple_articles_action(request, Article.ACCEPTED)


@author_required
@login_required
def multiple_articles_action_reject(request):
    return _multiple_articles_action(request, Article.REJECTED)


@author_required
@login_required
def multiple_articles_action_duplicated(request):
    return _multiple_articles_action(request, Article.DUPLICATED)


@author_required
@login_required
def save_data_extraction(request):
    try:
        review = get_object_or_404(Review, pk=request.POST["review-id"])
        article_id = request.POST["article-id"]
        field_id = request.POST["field-id"]
        value = request.POST["value"]
        field = get_object_or_404(DataExtractionField, pk=field_id, review=review)
        if field.field_type == DataExtractionField.SELECT_MANY_FIELD:
            # The legacy form posts one lookup id per click and expects it to be toggled.
            extraction.toggle_select_value(
                review=review, article_id=article_id, field_id=field_id, lookup_id=value, actor=request.user
            )
        else:
            extraction.set_value(
                review=review, article_id=article_id, field_id=field_id, value=value, actor=request.user
            )
        return HttpResponse()
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    except KeyError:
        return HttpResponseBadRequest()


@author_required
@login_required
def save_data_extraction_status(request):
    try:
        review = get_object_or_404(Review, pk=request.POST["review-id"])
        extraction.mark_done(
            review=review, article_id=request.POST.get("article-id"), done=request.POST.get("action") == "mark_as_done"
        )
        return HttpResponse()
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    except KeyError:
        return HttpResponseBadRequest()


@author_required
@login_required
def find_duplicates(request):
    review_id = request.GET["review-id"]
    review = Review.objects.get(pk=review_id)
    duplicates = studies.find_duplicates(review)
    return render(request, "conducting/partial_conducting_find_duplicates.html", {"duplicates": duplicates})


@author_required
@login_required
def resolve_duplicated(request):
    try:
        review = get_object_or_404(Review, pk=request.POST["review-id"])
        studies.resolve_duplicates(review=review, article_ids=[request.POST["article-id"]], actor=request.user)
        return HttpResponse()
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    except KeyError:
        return HttpResponseBadRequest()


@author_required
@login_required
def resolve_all(request):
    try:
        review = get_object_or_404(Review, pk=request.POST["review-id"])
        marked = studies.resolve_duplicates(review=review, actor=request.user)
        return HttpResponse(",".join(str(article.pk) for article in marked))
    except (DomainError, KeyError):
        return HttpResponseBadRequest()


@author_required
@login_required
def new_article(request):
    review_id = request.GET["review-id"]
    source_id = request.GET["source-id"]
    review = Review.objects.get(pk=review_id)
    source = Source.objects.get(pk=source_id)
    article = Article(review=review, source=source)
    return render(request, "conducting/partial_conducting_article_details.html", {"article": article})


@author_required
@login_required
def data_analysis(request, username, review_name):
    review = get_object_or_404(Review, name=review_name, author__username__iexact=username)
    return render(request, "conducting/conducting_data_analysis.html", {"review": review})


@author_required
@login_required
def articles_selection_chart(request):
    review = get_object_or_404(Review, pk=request.GET["review-id"])
    rows = analytics.selection_by_source(review)
    return HttpResponse(",".join("{source}:{total}:{accepted}".format(**row) for row in rows))


@author_required
@login_required
def articles_per_year(request):
    review = get_object_or_404(Review, pk=request.GET["review-id"])
    rows = analytics.final_selection_by_year(review)
    return HttpResponse(",".join(f"{row['year']}:{row['count']}" for row in rows if row["year"] is not None))


@author_required
@login_required
@require_POST
def add_source_string(request):
    review_id = request.POST.get("review-id")
    review = get_object_or_404(Review, pk=review_id)
    source_ids = request.POST.getlist("source")
    for source_id in source_ids:
        try:
            source = Source.objects.get(pk=source_id)
            exists = SearchSession.objects.filter(review=review, source=source).exists()
            if not exists:
                search_session = SearchSession(review=review, source=source)
                search_session.save()
        except Source.DoesNotExist:
            pass
    review.save()
    messages.success(request, "Sources search string successfully added to the review!")
    return redirect(r("search_studies", args=(review.author.username, review.name)))


def _xls_response(filename, columns, rows):
    response = HttpResponse(content_type="application/ms-excel")
    response["Content-Disposition"] = "attachment; filename={0}".format(filename)
    wb = xlwt.Workbook(encoding="utf-8")
    ws = wb.add_sheet("Articles")

    bold = xlwt.XFStyle()
    bold.font.bold = True
    for col_num, column in enumerate(columns):
        ws.write(0, col_num, column, bold)
        ws.col(col_num).width = 2000

    plain = xlwt.XFStyle()
    for row_num, row in enumerate(rows, start=1):
        for col_num, column in enumerate(columns):
            value = row[column]
            if hasattr(value, "tzinfo") and value.tzinfo is not None:
                value = value.replace(tzinfo=None)
            ws.write(row_num, col_num, value, plain)

    wb.save(response)
    return response


@author_required
@login_required
@require_POST
def export_results(request):
    review = get_object_or_404(Review, pk=request.POST.get("review-id"))
    columns, rows = reports.articles_rows(review)
    return _xls_response("articles.xls", columns, rows)


@author_required
@login_required
@require_POST
def export_data_extraction(request):
    review = get_object_or_404(Review, pk=request.POST.get("review-id"))
    columns, rows = reports.extraction_rows(review)
    return _xls_response("data_extraction.xls", columns, rows)
