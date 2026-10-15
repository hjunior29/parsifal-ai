"""
Mapping-study support beyond classification: the known-paper test set used to evaluate the search and the
process self-assessment checklist (Petersen et al. 2015, Table 8).
"""

from django.utils.text import slugify

from parsifal.apps.reviews.models import ProcessChecklistItem, ReviewTestSetArticle
from parsifal.apps.reviews.services._common import check_length, get_child, require

# (key, phase, label) — the 26 actions of Petersen et al. (2015) Table 8.
PETERSEN_CHECKLIST = (
    ("need_motivation", "Need for map", "Motivate the need and relevance"),
    ("need_objectives", "Need for map", "Define objectives and questions"),
    ("need_audience", "Need for map", "Consult with target audience to define questions"),
    ("search_snowballing", "Study identification", "Snowballing"),
    ("search_manual", "Study identification", "Manual search"),
    ("search_database", "Study identification", "Conduct database search"),
    ("develop_picoc", "Study identification", "Develop the search with PICO(C)"),
    ("develop_experts", "Study identification", "Consult librarians or experts"),
    ("develop_iterative", "Study identification", "Iteratively try finding more relevant papers"),
    ("develop_known_papers", "Study identification", "Keywords from known papers"),
    ("develop_standards", "Study identification", "Use standards, encyclopedias and thesaurus"),
    ("evaluate_test_set", "Study identification", "Evaluate the search with a test set of known papers"),
    ("evaluate_expert", "Study identification", "Expert evaluates the search result"),
    ("evaluate_author_pages", "Study identification", "Search web pages of key authors"),
    ("evaluate_test_retest", "Study identification", "Test-retest the search"),
    ("inclusion_objective_criteria", "Study identification", "Identify objective inclusion/exclusion criteria"),
    ("inclusion_additional_reviewer", "Study identification", "Add an additional reviewer; resolve disagreements"),
    ("inclusion_decision_rules", "Study identification", "Define decision rules for inclusion"),
    ("extraction_objective_criteria", "Extraction and classification", "Identify objective criteria for extraction"),
    ("extraction_obscure_bias", "Extraction and classification", "Obscure information that could bias"),
    (
        "extraction_additional_reviewer",
        "Extraction and classification",
        "Add an additional reviewer; resolve disagreements",
    ),
    ("extraction_test_retest", "Extraction and classification", "Test-retest the extraction"),
    ("classification_research_type", "Extraction and classification", "Classify by research type"),
    ("classification_research_method", "Extraction and classification", "Classify by research method"),
    ("classification_venue_type", "Extraction and classification", "Classify by venue type"),
    ("validity_discussion", "Validity", "Discuss validity threats and limitations"),
)

CHECKLIST_KEYS = {key for key, _phase, _label in PETERSEN_CHECKLIST}


# ---------------------------------------------------------------------------------------------------------------------
# Test set of known papers
# ---------------------------------------------------------------------------------------------------------------------


def add_test_set_article(*, review, title, doi="", notes=""):
    require(title, field="title")
    check_length(title, 1000, field="title")
    check_length(doi or "", 100, field="doi")
    check_length(notes or "", 500, field="notes")
    item = ReviewTestSetArticle.objects.create(review=review, title=title, doi=(doi or "").strip(), notes=notes or "")
    match_test_set(review=review)
    return item


def update_test_set_article(*, review, item_id, title=None, doi=None, notes=None):
    item = get_child(review.test_set, item_id, label="Test-set article")
    if title is not None:
        require(title, field="title")
        item.title = check_length(title, 1000, field="title")
    if doi is not None:
        item.doi = check_length(doi.strip(), 100, field="doi")
    if notes is not None:
        item.notes = check_length(notes, 500, field="notes")
    item.save()
    match_test_set(review=review)
    return item


def remove_test_set_article(*, review, item_id):
    get_child(review.test_set, item_id, label="Test-set article").delete()


def match_test_set(*, review):
    """Link each known paper to an imported article by DOI (case-insensitive) or by normalised title."""
    articles = list(review.article_set.only("id", "title", "doi"))
    by_doi = {a.doi.strip().lower(): a for a in articles if a.doi}
    by_title = {}
    for article in articles:
        by_title.setdefault(slugify(article.title or ""), article)
    for item in review.test_set.all():
        match = None
        if item.doi:
            match = by_doi.get(item.doi.lower())
        if match is None:
            match = by_title.get(slugify(item.title))
        if item.matched_article_id != (match.pk if match else None):
            item.matched_article = match
            item.save(update_fields=["matched_article"])
    return test_set_report(review)


def test_set_report(review):
    items = list(review.test_set.select_related("matched_article"))
    found = sum(1 for item in items if item.matched_article_id)
    return {
        "total": len(items),
        "found": found,
        "recall": (found / len(items)) if items else None,
        "items": items,
    }


# ---------------------------------------------------------------------------------------------------------------------
# Process checklist (Petersen Table 8)
# ---------------------------------------------------------------------------------------------------------------------


def checklist(review):
    stored = {item.key: item for item in review.checklist_items.all()}
    rows = []
    applied = 0
    for key, phase, label in PETERSEN_CHECKLIST:
        item = stored.get(key)
        is_applied = bool(item and item.applied)
        applied += is_applied
        rows.append(
            {"key": key, "phase": phase, "label": label, "applied": is_applied, "notes": item.notes if item else ""}
        )
    return {
        "applied": applied,
        "total": len(PETERSEN_CHECKLIST),
        "ratio": applied / len(PETERSEN_CHECKLIST),
        "items": rows,
    }


def set_checklist_item(*, review, key, applied, notes=None):
    if key not in CHECKLIST_KEYS:
        raise_unknown_key(key)
    defaults = {"applied": bool(applied)}
    if notes is not None:
        defaults["notes"] = check_length(notes, 500, field="notes")
    ProcessChecklistItem.objects.update_or_create(review=review, key=key, defaults=defaults)
    return checklist(review)


def raise_unknown_key(key):
    from parsifal.apps.core.exceptions import ValidationError

    raise ValidationError(f"Unknown checklist action {key!r}.", field="key")
