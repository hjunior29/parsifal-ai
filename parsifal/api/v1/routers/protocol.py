from ninja import Router

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.common import OrderIn
from parsifal.api.v1.schemas.protocol import (
    CriteriaIn,
    CriteriaOut,
    CriteriaUpdateIn,
    KeywordIn,
    KeywordOut,
    KeywordUpdateIn,
    QuestionIn,
    QuestionOut,
    QuestionUpdateIn,
    SearchStringIn,
    SearchStringOut,
    SourceAddIn,
    SourceOut,
    SourceSearchStringOut,
    SourceUpdateIn,
)
from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.services import protocol, search

router = Router(tags=["protocol"])

# ---------------------------------------------------------------------------------------------------------------------
# Research questions
# ---------------------------------------------------------------------------------------------------------------------


@router.get("/reviews/{int:review_id}/questions", response=list[QuestionOut], operation_id="questions_list")
def questions_list(request, review_id: int):
    return get_review(request, review_id).research_questions.all()


@router.post("/reviews/{int:review_id}/questions", response={201: QuestionOut}, operation_id="questions_create")
def questions_create(request, review_id: int, payload: QuestionIn):
    review = get_review(request, review_id)
    return 201, protocol.add_question(review=review, description=payload.description, parent_id=payload.parent_id)


@router.patch(
    "/reviews/{int:review_id}/questions/{int:question_id}", response=QuestionOut, operation_id="questions_update"
)
def questions_update(request, review_id: int, question_id: int, payload: QuestionUpdateIn):
    review = get_review(request, review_id)
    return protocol.update_question(review=review, question_id=question_id, description=payload.description)


@router.delete(
    "/reviews/{int:review_id}/questions/{int:question_id}", response={204: None}, operation_id="questions_delete"
)
def questions_delete(request, review_id: int, question_id: int):
    protocol.remove_question(review=get_review(request, review_id), question_id=question_id)
    return 204, None


@router.put("/reviews/{int:review_id}/questions/order", response=list[QuestionOut], operation_id="questions_reorder")
def questions_reorder(request, review_id: int, payload: OrderIn):
    return protocol.reorder_questions(review=get_review(request, review_id), ordered_ids=payload.ids)


# ---------------------------------------------------------------------------------------------------------------------
# Keywords and search string
# ---------------------------------------------------------------------------------------------------------------------


@router.get("/reviews/{int:review_id}/keywords", response=list[KeywordOut], operation_id="keywords_list")
def keywords_list(request, review_id: int):
    return get_review(request, review_id).keywords.filter(synonym_of=None).prefetch_related("synonyms")


@router.post("/reviews/{int:review_id}/keywords", response={201: KeywordOut}, operation_id="keywords_create")
def keywords_create(request, review_id: int, payload: KeywordIn):
    review = get_review(request, review_id)
    keyword = protocol.add_keyword(
        review=review, description=payload.description, related_to=payload.related_to, synonyms=payload.synonyms
    )
    return 201, keyword


@router.patch(
    "/reviews/{int:review_id}/keywords/{int:keyword_id}", response=KeywordOut, operation_id="keywords_update"
)
def keywords_update(request, review_id: int, keyword_id: int, payload: KeywordUpdateIn):
    review = get_review(request, review_id)
    return protocol.update_keyword(review=review, keyword_id=keyword_id, **payload.dict(exclude_unset=True))


@router.delete(
    "/reviews/{int:review_id}/keywords/{int:keyword_id}", response={204: None}, operation_id="keywords_delete"
)
def keywords_delete(request, review_id: int, keyword_id: int):
    protocol.remove_keyword(review=get_review(request, review_id), keyword_id=keyword_id)
    return 204, None


@router.post(
    "/reviews/{int:review_id}/keywords/import-picoc", response=list[KeywordOut], operation_id="keywords_import_picoc"
)
def keywords_import_picoc(request, review_id: int):
    """Create keywords from the comma-separated PICO fields of the review."""
    return protocol.import_picoc_keywords(review=get_review(request, review_id))


@router.get("/reviews/{int:review_id}/search-string", response=SearchStringOut, operation_id="search_string_get")
def search_string_get(request, review_id: int):
    session = protocol.get_generic_search_string(get_review(request, review_id))
    return SearchStringOut(search_string=session.search_string if session else "")


@router.put("/reviews/{int:review_id}/search-string", response=SearchStringOut, operation_id="search_string_set")
def search_string_set(request, review_id: int, payload: SearchStringIn):
    review = get_review(request, review_id)
    return protocol.set_generic_search_string(review=review, search_string=payload.search_string)


@router.post(
    "/reviews/{int:review_id}/search-string/generate", response=SearchStringOut, operation_id="search_string_generate"
)
def search_string_generate(request, review_id: int):
    """Build the Boolean string from keywords and synonyms (does not save it)."""
    return SearchStringOut(search_string=protocol.generate_search_string(get_review(request, review_id)))


# ---------------------------------------------------------------------------------------------------------------------
# Sources and per-source search strings
# ---------------------------------------------------------------------------------------------------------------------


@router.get("/reviews/{int:review_id}/sources", response=list[SourceOut], operation_id="review_sources_list")
def review_sources_list(request, review_id: int):
    return get_review(request, review_id).sources.all()


@router.post("/reviews/{int:review_id}/sources", response={201: SourceOut}, operation_id="review_sources_add")
def review_sources_add(request, review_id: int, payload: SourceAddIn):
    review = get_review(request, review_id)
    if payload.source_id is not None:
        return 201, protocol.attach_source(review=review, source_id=payload.source_id)
    if payload.name:
        return 201, protocol.create_source(review=review, name=payload.name, url=payload.url)
    raise ValidationError("Provide source_id (default library) or name/url (custom source).")


@router.patch(
    "/reviews/{int:review_id}/sources/{int:source_id}", response=SourceOut, operation_id="review_sources_update"
)
def review_sources_update(request, review_id: int, source_id: int, payload: SourceUpdateIn):
    review = get_review(request, review_id)
    return protocol.update_source(review=review, source_id=source_id, **payload.dict(exclude_unset=True))


@router.delete(
    "/reviews/{int:review_id}/sources/{int:source_id}", response={204: None}, operation_id="review_sources_remove"
)
def review_sources_remove(request, review_id: int, source_id: int):
    """Detach a source. For default libraries this also deletes the review's articles imported from it."""
    protocol.detach_source(review=get_review(request, review_id), source_id=source_id)
    return 204, None


@router.get(
    "/reviews/{int:review_id}/sources/search-strings",
    response=list[SourceSearchStringOut],
    operation_id="source_search_strings_list",
)
def source_search_strings_list(request, review_id: int):
    return search.list_source_search_strings(get_review(request, review_id))


@router.put(
    "/reviews/{int:review_id}/sources/{int:source_id}/search-string",
    response=SourceSearchStringOut,
    operation_id="source_search_string_set",
)
def source_search_string_set(request, review_id: int, source_id: int, payload: SearchStringIn):
    review = get_review(request, review_id)
    return search.set_source_search_string(review=review, source_id=source_id, search_string=payload.search_string)


@router.post(
    "/reviews/{int:review_id}/sources/{int:source_id}/search-string/copy-generic",
    response=SourceSearchStringOut,
    operation_id="source_search_string_copy_generic",
)
def source_search_string_copy_generic(request, review_id: int, source_id: int):
    return search.copy_generic_search_string(review=get_review(request, review_id), source_id=source_id)


@router.delete(
    "/reviews/{int:review_id}/sources/{int:source_id}/search-string",
    response={204: None},
    operation_id="source_search_string_delete",
)
def source_search_string_delete(request, review_id: int, source_id: int):
    search.remove_source_search_string(review=get_review(request, review_id), source_id=source_id)
    return 204, None


# ---------------------------------------------------------------------------------------------------------------------
# Selection criteria
# ---------------------------------------------------------------------------------------------------------------------


@router.get("/reviews/{int:review_id}/criteria", response=list[CriteriaOut], operation_id="criteria_list")
def criteria_list(request, review_id: int):
    return get_review(request, review_id).selectioncriteria_set.all()


@router.post("/reviews/{int:review_id}/criteria", response={201: CriteriaOut}, operation_id="criteria_create")
def criteria_create(request, review_id: int, payload: CriteriaIn):
    review = get_review(request, review_id)
    return 201, protocol.add_criteria(
        review=review, description=payload.description, criteria_type=payload.criteria_type
    )


@router.patch(
    "/reviews/{int:review_id}/criteria/{int:criteria_id}", response=CriteriaOut, operation_id="criteria_update"
)
def criteria_update(request, review_id: int, criteria_id: int, payload: CriteriaUpdateIn):
    review = get_review(request, review_id)
    return protocol.update_criteria(review=review, criteria_id=criteria_id, description=payload.description)


@router.delete(
    "/reviews/{int:review_id}/criteria/{int:criteria_id}", response={204: None}, operation_id="criteria_delete"
)
def criteria_delete(request, review_id: int, criteria_id: int):
    protocol.remove_criteria(review=get_review(request, review_id), criteria_id=criteria_id)
    return 204, None
