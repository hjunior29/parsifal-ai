import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.forms.formsets import formset_factory
from django.forms.models import inlineformset_factory
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse as r
from django.utils.html import escape
from django.views.decorators.http import require_POST

from parsifal.apps.core.exceptions import DomainError
from parsifal.apps.reviews.decorators import author_required
from parsifal.apps.reviews.models import (
    DataExtraction,
    DataExtractionField,
    DataExtractionLookup,
    Keyword,
    QualityAnswer,
    QualityQuestion,
    Question,
    Review,
    SelectionCriteria,
    Source,
)
from parsifal.apps.reviews.planning.forms import KeywordForm, SynonymForm
from parsifal.apps.reviews.services import protocol as protocol_services, reviews

NEW = ("", "None")  # the id a row's form sends for an object not saved yet


def child(queryset, pk):
    """The review's object with this primary key: 404 when it does not exist or belongs to another review."""
    try:
        return queryset.get(pk=pk)
    except (queryset.model.DoesNotExist, ValueError, TypeError):
        raise Http404


@author_required
@login_required
def planning(request, username, review_name):
    return redirect(r("protocol", args=(username, review_name)))


@author_required
@login_required
def protocol(request, username, review_name):
    review = get_object_or_404(Review, name=review_name, author__username__iexact=username)
    return render(request, "planning/protocol.html", {"review": review})


@author_required
@login_required
def quality_assessment_checklist(request, username, review_name):
    review = get_object_or_404(Review, name=review_name, author__username__iexact=username)
    return render(request, "planning/quality_assessment_checklist.html", {"review": review})


@author_required
@login_required
def data_extraction_form(request, username, review_name):
    review = get_object_or_404(Review, name=review_name, author__username__iexact=username)
    empty_field = DataExtractionField()
    return render(
        request,
        "planning/data_extraction_form.html",
        {"review": review, "empty_field": empty_field},
    )


# ==============================================================================
# OBJECTIVE
# ==============================================================================


@author_required
@login_required
@require_POST
def save_objective(request):
    try:
        objective = request.POST["objective"]
        review = request.review
        if len(objective) > 1000:
            return HttpResponseBadRequest(
                "The review objectives should not exceed 1000 characters. The given objectives have %s characters."
                % len(objective)
            )
        else:
            review.objective = objective
            review.save()
            return HttpResponse("Your review have been saved successfully!")
    except Exception:
        return HttpResponseBadRequest()


# ==============================================================================
# QUESTION
# ==============================================================================


@author_required
@login_required
@require_POST
def save_question(request):
    """
    Function used via Ajax request only.
    This function takes a review question form and save on the database
    """
    try:
        question_id = request.POST["question-id"]
        description = request.POST["description"]
        review = request.review
        if question_id in NEW:
            question = Question(review=review)
        else:
            question = child(review.research_questions, question_id)
        question.question = description[:500]
        question.save()
        return render(request, "planning/partial_planning_question.html", {"question": question})
    except Exception:
        return HttpResponseBadRequest()


def save_order(queryset, orders):
    """Apply "id:order,id:order" to the review's objects; rows still being added ("None") are skipped."""
    with transaction.atomic():
        for item in orders.split(","):
            if item:
                pk, order = item.split(":")
                if pk in NEW:
                    continue
                obj = child(queryset, pk)
                obj.order = int(order)
                obj.save(update_fields=["order"])


@author_required
@login_required
@require_POST
def save_question_order(request):
    try:
        save_order(request.review.research_questions, request.POST["orders"])
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def add_or_edit_question(request):
    """
    Function used via Ajax request only.
    This functions adds a new secondary question to the review.
    """
    try:
        question_id = request.POST["question-id"]
        review = request.review
        if question_id in NEW:
            question = Question(review=review)
        else:
            question = child(review.research_questions, question_id)
        return render(request, "planning/partial_planning_question_form.html", {"question": question})
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def remove_question(request):
    """
    Function used via Ajax request only.
    This function removes a secondary question from the review.
    """
    try:
        question_id = request.POST["question-id"]
        if question_id != "None":
            child(request.review.research_questions, question_id).delete()
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()


# ==============================================================================
# PICOC
# ==============================================================================


@author_required
@login_required
@require_POST
def save_picoc(request):
    try:
        review = request.review
        review.population = request.POST["population"][:200]
        review.intervention = request.POST["intervention"][:200]
        review.comparison = request.POST["comparison"][:200]
        review.outcome = request.POST["outcome"][:200]
        review.context = request.POST["context"][:200]
        review.save()
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()


# ==============================================================================
# KEYWORDS/SYNONYM
# ==============================================================================


def extract_keywords(review, pico):
    if pico == Keyword.POPULATION:
        keywords = review.population
    elif pico == Keyword.INTERVENTION:
        keywords = review.intervention
    elif pico == Keyword.COMPARISON:
        keywords = review.comparison
    elif pico == Keyword.OUTCOME:
        keywords = review.outcome
    else:
        keywords = ""
    keyword_list = keywords.split(",")
    keyword_objects = []
    for term in keyword_list:
        if len(term) > 0:
            keyword = Keyword(review=review, description=term.strip(), related_to=pico)
            if keyword.description not in review.get_keywords().values_list("description", flat=True):
                keyword.save()
                keyword_objects.append(keyword)
    return keyword_objects


@author_required
@login_required
@require_POST
def import_pico_keywords(request):
    try:
        review = request.review
        keywords = []

        keywords += extract_keywords(review, Keyword.POPULATION)
        keywords += extract_keywords(review, Keyword.INTERVENTION)
        keywords += extract_keywords(review, Keyword.COMPARISON)
        keywords += extract_keywords(review, Keyword.OUTCOME)

        html = ""

        for keyword in keywords:
            html += render_to_string("planning/partial_keyword.html", {"keyword": keyword}, request)
        return HttpResponse(html)
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def remove_keyword(request):
    try:
        keyword = child(request.review.keywords, request.POST["keyword-id"])
        for synonym in keyword.synonyms.all():
            synonym.delete()
        keyword.delete()
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()


@transaction.atomic
@author_required
@login_required
def add_keyword(request):
    review = request.review
    SynonymFormSet = formset_factory(SynonymForm)
    response = {}
    if request.method == "POST":
        form = KeywordForm(request.POST)
        formset = SynonymFormSet(request.POST, prefix="synonym")
        if form.is_valid() and formset.is_valid():
            form.instance.review = review
            keyword = form.save()
            for form in formset:
                if form.instance.description:
                    form.instance.review = review
                    form.instance.synonym_of = keyword
                    form.save()
            response["status"] = "ok"
            response["html"] = render_to_string("planning/partial_keyword.html", {"keyword": keyword}, request)
            dump = json.dumps(response)
            return HttpResponse(dump, content_type="application/json")
        else:
            response["status"] = "validation_error"
    else:
        form = KeywordForm()
        formset = SynonymFormSet(prefix="synonym")
        response["status"] = "new"
    response["html"] = render_to_string(
        "planning/partial_keyword_form.html",
        {"review": review, "form": form, "formset": formset},
        request,
    )
    dump = json.dumps(response)
    return HttpResponse(dump, content_type="application/json")


@transaction.atomic
@author_required
@login_required
def edit_keyword(request):
    review = request.review
    keyword = child(review.keywords, request.POST.get("keyword-id") or request.GET.get("keyword-id"))

    SynonymFormSet = inlineformset_factory(Keyword, Keyword, SynonymForm, extra=1)
    response = {}
    if request.method == "POST":
        form = KeywordForm(request.POST, instance=keyword)
        formset = SynonymFormSet(request.POST, instance=keyword, prefix="synonym")
        if form.is_valid() and formset.is_valid():
            form.instance.review = review
            keyword = form.save()
            for form in formset:
                form.instance.review = review
                form.instance.synonym_of = keyword
            formset.save()
            response["status"] = "ok"
            response["html"] = render_to_string("planning/partial_keyword.html", {"keyword": keyword}, request)
            dump = json.dumps(response)
            return HttpResponse(dump, content_type="application/json")
        else:
            response["status"] = "validation_error"
    else:
        form = KeywordForm(instance=keyword)
        formset = SynonymFormSet(instance=keyword, prefix="synonym")
        response["status"] = "new"
    response["html"] = render_to_string(
        "planning/partial_keyword_form.html",
        {"review": review, "form": form, "formset": formset},
        request,
    )
    dump = json.dumps(response)
    return HttpResponse(dump, content_type="application/json")


# ==============================================================================
# SEARCH STRING
# ==============================================================================


@author_required
@login_required
def generate_search_string(request):
    """
    Function used via Ajax request only.
    Still have to refactor this function. This is just a first approach.
    """
    review = request.review

    keywords = []
    for key, value in Keyword.RELATED_TO:
        synonyms = []
        for keyword in review.keywords.filter(related_to=key, synonym_of=None):
            synonyms.append('"{0}"'.format(keyword.description))
            for synonym in keyword.synonyms.all():
                synonyms.append('"{0}"'.format(synonym.description))
        if any(synonyms):
            keywords.append("({0})".format(" OR ".join(synonyms)))

    return HttpResponse(" AND ".join(keywords))


@author_required
@login_required
@require_POST
def save_generic_search_string(request):
    try:
        search_string = request.POST["search-string"]
        review = request.review
        generic_search_string = review.get_generic_search_string()
        generic_search_string.search_string = search_string
        generic_search_string.save()
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()


# ==============================================================================
# SOURCE
# ==============================================================================


def html_source(source):
    html = '<tr source-id="' + str(source.id) + '"><td>' + escape(source.name) + "</td>"
    if source.url:
        html += '<td><a href="' + escape(source.url) + '" target="_blank">' + escape(source.url) + "</a></td>"
    else:
        html += "<td>" + escape(source.url) + "</td>"
    if source.is_default:
        html += '<td class="text-right"><span data-toggle="tooltip" data-placement="top" data-container="body" title="It\'s not possible to edit Digital Library\'s details"><button type="button" class="btn btn-sm btn-warning" disabled>edit</button></span> <button type="button" class="btn btn-danger btn-sm js-start-remove">remove</a></td></tr>'  # noqa
    else:
        html += '<td class="text-right"><button type="button" class="btn btn-sm btn-warning btn-edit-source"><span class="glyphicon glyphicon-pencil"></span> edit</button> <button type="button" class="btn btn-danger btn-sm js-start-remove"><span class="glyphicon glyphicon-trash"></span> remove</a></td></tr>'  # noqa
    return html


@author_required
@login_required
@require_POST
def save_source(request):
    """
    Function used via Ajax request only.
    This function adds a new source to the source list of the review.
    To add the source successfully the logged in user must be the author or a co-author
    of the review.
    If the request receives a source_id, that means the source already exist so the function
    will just edit the existing source and save the model.
    """
    try:
        source_id = request.POST["source-id"]
        name = request.POST["name"][:100]
        url = request.POST["url"][:200]
        if source_id:
            source = protocol_services.update_source(review=request.review, source_id=source_id, name=name, url=url)
        else:
            source = protocol_services.create_source(review=request.review, name=name, url=url)
        return HttpResponse(html_source(source))
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def remove_source_from_review(request):
    """Detach one of the review's sources (a custom source is deleted, with the review's studies from it)."""
    try:
        protocol_services.detach_source(review=request.review, source_id=request.POST["source-id"])
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
def suggested_sources(request):
    try:
        review = request.review
        default_sources = Source.objects.filter(is_default=True)
        sources = filter(lambda s: s not in review.sources.all(), default_sources)
        return_html = ""
        for source in sources:
            return_html += (
                '''
            <tr>
              <td>
                <input type="checkbox" value="'''
                + str(source.id)
                + """" name="source-id">
              </td>
              <td>"""
                + escape(source.name)
                + '''</td>
              <td>
                <a href="'''
                + escape(source.url)
                + """" target="_blank">"""
                + escape(source.url)
                + """</a>
              </td>
            </tr>"""
            )
        return HttpResponse(return_html)
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def add_suggested_sources(request):
    try:
        source_ids = request.POST.getlist("source-id")
        review = request.review
        return_html = ""
        for source_id in source_ids:
            source = child(Source.objects.filter(is_default=True), source_id)
            review.sources.add(source)
            return_html += html_source(source)
        review.save()
        return HttpResponse(return_html)
    except Exception:
        return HttpResponseBadRequest()


# ==============================================================================
# INCLUSION/EXCLUSION CRITERIA
# ==============================================================================


@author_required
@login_required
@require_POST
def add_criteria(request):
    try:
        description = request.POST["criteria"]
        criteria_type = request.POST["criteria-type"]
        criteria = SelectionCriteria(review=request.review, description=description, criteria_type=criteria_type)
        criteria.save()
        return render(request, "planning/partial_criteria.html", {"criteria": criteria})
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def save_inclusion_rule(request):
    """Whether a study must meet all the inclusion criteria or at least one (Include and Screen with AI follow it)."""
    review = request.review
    try:
        reviews.update_review(review=review, inclusion_rule=request.POST.get("inclusion-rule"))
    except DomainError as error:
        return HttpResponseBadRequest(str(error))
    return HttpResponse(review.get_inclusion_rule_display())


@author_required
@login_required
@require_POST
def remove_criteria(request):
    try:
        criteria = [child(request.review.selectioncriteria_set, pk) for pk in request.POST["criteria-ids"].split(",")]
        for item in criteria:
            item.delete()
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()


# ==============================================================================
# QUALITY ASSESSMENT FUNCTIONS
# ==============================================================================


@author_required
@login_required
def add_quality_assessment_question(request):
    try:
        quality_question = QualityQuestion()
        return render(
            request,
            "planning/partial_quality_assessment_question_form.html",
            {"quality_question": quality_question},
        )
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
def edit_quality_assessment_question(request):
    try:
        quality_question = child(request.review.qualityquestion_set, request.GET["quality-question-id"])
        return render(
            request,
            "planning/partial_quality_assessment_question_form.html",
            {"quality_question": quality_question},
        )
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def save_quality_assessment_question(request):
    try:
        description = request.POST["description"]
        quality_question_id = request.POST["quality-question-id"]

        review = request.review

        if quality_question_id in NEW:
            quality_question = QualityQuestion(review=review)
        else:
            quality_question = child(review.qualityquestion_set, quality_question_id)

        quality_question.description = description
        quality_question.save()

        return render(
            request,
            "planning/partial_quality_assessment_question.html",
            {"quality_question": quality_question},
        )
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def save_quality_assessment_question_order(request):
    try:
        save_order(request.review.qualityquestion_set, request.POST["orders"])
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def remove_quality_assessment_question(request):
    try:
        child(request.review.qualityquestion_set, request.POST["quality-question-id"]).delete()
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
def add_quality_assessment_answer(request):
    try:
        quality_answer = QualityAnswer()
        return render(
            request,
            "planning/partial_quality_assessment_answer_form.html",
            {"quality_answer": quality_answer},
        )
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
def edit_quality_assessment_answer(request):
    try:
        quality_answer = child(request.review.qualityanswer_set, request.GET["quality-answer-id"])
        return render(
            request,
            "planning/partial_quality_assessment_answer_form.html",
            {"quality_answer": quality_answer},
        )
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def save_quality_assessment_answer(request):
    try:
        description = request.POST["description"]
        weight = request.POST["weight"]
        quality_answer_id = request.POST["quality-answer-id"]

        weight = weight.replace(",", ".")
        try:
            weight = float(weight)
        except Exception:
            weight = 0.0

        review = request.review

        if quality_answer_id in NEW:
            quality_answer = QualityAnswer(review=review)
        else:
            quality_answer = child(review.qualityanswer_set, quality_answer_id)

        quality_answer.description = description
        quality_answer.weight = weight
        quality_answer.save()

        return render(
            request,
            "planning/partial_quality_assessment_answer.html",
            {"quality_answer": quality_answer},
        )
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def remove_quality_assessment_answer(request):
    try:
        child(request.review.qualityanswer_set, request.POST["quality-answer-id"]).delete()
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def add_suggested_answer(request):
    try:
        review = request.review
        if not review.get_quality_assessment_answers():
            html_answers = ""
            for answer, value in QualityAnswer.SUGGESTED_ANSWERS:
                quality_answer = QualityAnswer(review=review, description=answer, weight=value)
                quality_answer.save()
                html_answers += """<tr oid="{0}">
                  <td>{1}</td>
                  <td>{2}</td>
                  <td>
                    <button type="button" class="btn btn-warning btn-sm btn-edit-quality-answer">edit</button>
                    <button type="button" class="btn btn-danger btn-sm btn-remove-quality-answer">remove</button>
                  </td>
                </tr>""".format(
                    quality_answer.id, quality_answer.description, quality_answer.weight
                )
            return HttpResponse(html_answers)
        else:
            return HttpResponseBadRequest()
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
def calculate_max_score(request):
    try:
        max_score = request.review.calculate_quality_assessment_max_score()
        return HttpResponse(max_score)
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def save_cutoff_score(request):
    try:
        cutoff_score = request.POST["cutoff-score"]
        review = request.review
        review.quality_assessment_cutoff_score = float(cutoff_score)
        review.save()
        return HttpResponse("Cutoff score saved successfully!")
    except Exception:
        return HttpResponseBadRequest("Invalid value.")


# =====================================================================================================================
# DATA EXTRACTION
# =====================================================================================================================


@author_required
@login_required
def add_new_data_extraction_field(request):
    field = DataExtractionField()
    return render(request, "planning/partial_data_extraction_field_form.html", {"field": field})


@author_required
@login_required
def edit_data_extraction_field(request):
    field = child(request.review.dataextractionfield_set, request.GET.get("field-id"))
    return render(request, "planning/partial_data_extraction_field_form.html", {"field": field})


@author_required
@login_required
@require_POST
def save_data_extraction_field(request):
    try:
        description = request.POST["description"]
        field_type = request.POST["field-type"]
        lookup_values = request.POST["lookup-values"]
        field_id = request.POST["field-id"]

        if not field_type and not description:
            return HttpResponseBadRequest("Description and Type are required fields.")

        lookup_values = lookup_values.split("\n")
        lookup_values = list(set(lookup_values))

        for i in range(0, len(lookup_values)):
            lookup_values[i] = lookup_values[i].strip()

        review = request.review

        if field_id in NEW:
            field = DataExtractionField(review=review)
        else:
            field = child(review.dataextractionfield_set, field_id)
            if field.field_type != field_type:
                try:
                    data_extractions = DataExtraction.objects.filter(field=field)
                    for data_extraction in data_extractions:
                        data_extraction.value = ""
                        data_extraction.select_values.clear()
                        data_extraction.save()
                except Exception:
                    pass

        field.description = description
        field.field_type = field_type
        field.save()

        if field.is_select_field():
            for value in lookup_values:
                if value:
                    DataExtractionLookup.objects.get_or_create(field=field, value=value)
            for select_value in field.get_select_values():
                if select_value.value not in lookup_values:
                    select_value.delete()
        else:
            for select_value in field.get_select_values():
                select_value.delete()
        return render(request, "planning/partial_data_extraction_field.html", {"field": field})
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def save_data_extraction_field_order(request):
    try:
        save_order(request.review.dataextractionfield_set, request.POST["orders"])
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()


@author_required
@login_required
@require_POST
def remove_data_extraction_field(request):
    try:
        field = child(request.review.dataextractionfield_set, request.POST["field-id"])
        select_values = field.get_select_values()
        for select_value in select_values:
            select_value.delete()
        field.delete()
        return HttpResponse()
    except Exception:
        return HttpResponseBadRequest()
