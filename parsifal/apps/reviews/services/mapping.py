"""
Mapping-study support beyond classification: the known-paper test set used to evaluate the search and the process
checklists: the self-assessment of Petersen et al. (2015, Table 8), and that of a rapid review (services.rapid).
"""

from django.utils.text import slugify

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import ProcessChecklistItem, ReviewEvent, ReviewTestSetArticle
from parsifal.apps.reviews.services import history, rapid
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

PETERSEN, RAPID = "petersen", "rapid"
# Each checklist as (key, group, label, the threat it brings): the threats are the rapid review's concessions'.
CATALOGS = {
    PETERSEN: tuple((key, phase, label, "") for key, phase, label in PETERSEN_CHECKLIST),
    RAPID: tuple((key, group, label, threat) for key, group, label, _type, threat in rapid.RAPID_CHECKLIST),
}
CHECKLIST_KEYS = {key for rows in CATALOGS.values() for key, *_rest in rows}
CHECKLIST_LABELS = {key: label for rows in CATALOGS.values() for key, _group, label, _threat in rows}

# What the History records of the test set (the search's evaluation) and of the process checklist.
TEST_SET = history.Kind("known study of the test set", ReviewEvent.SEARCH, ("title", "doi", "notes"))
CHECKLIST_ITEM = history.Kind("checklist action", ReviewEvent.REVIEW, ("applied", "notes"))
# The rapid review's checklist is its protocol (its concessions and their justification): changed once studies were
# imported, it is an amendment.
RAPID_ITEM = history.Kind(
    "rapid review checklist item", ReviewEvent.PLANNING, ("applied", "notes"), labels=(("notes", "Justification"),)
)


# ---------------------------------------------------------------------------------------------------------------------
# Test set of known papers
# ---------------------------------------------------------------------------------------------------------------------


def add_test_set_article(*, review, title, doi="", notes=""):
    require(title, field="title")
    check_length(title, 1000, field="title")
    check_length(doi or "", 100, field="doi")
    check_length(notes or "", 500, field="notes")
    item = ReviewTestSetArticle.objects.create(review=review, title=title, doi=(doi or "").strip(), notes=notes or "")
    TEST_SET.added(review, item)
    match_test_set(review=review)
    return item


def update_test_set_article(*, review, item_id, title=None, doi=None, notes=None):
    item = get_child(review.test_set, item_id, label="Test-set article")
    tracker = TEST_SET.track(item)
    if title is not None:
        require(title, field="title")
        item.title = check_length(title, 1000, field="title")
    if doi is not None:
        item.doi = check_length(doi.strip(), 100, field="doi")
    if notes is not None:
        item.notes = check_length(notes, 500, field="notes")
    item.save()
    TEST_SET.changed(review, tracker)
    match_test_set(review=review)
    return item


def remove_test_set_article(*, review, item_id):
    item = get_child(review.test_set, item_id, label="Test-set article")
    TEST_SET.removed(review, item)
    item.delete()


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


def _catalog_of(key):
    return next(catalog for catalog, rows in CATALOGS.items() if any(row[0] == key for row in rows))


def checklist(review, catalog=PETERSEN):
    """
    A checklist of the review (``catalog``: petersen, the default, or rapid — rapid reviews only): each item with its
    group (``phase``), whether it was applied, its notes (a rapid review's justification) and the threat it brings.
    """
    if catalog not in CATALOGS:
        raise ValidationError(f"catalog must be one of {', '.join(CATALOGS)}.", field="catalog")
    if catalog == RAPID:
        rapid.require_rapid(review)
    stored = {item.key: item for item in review.checklist_items.all()}
    rows = []
    applied = 0
    for key, phase, label, threat in CATALOGS[catalog]:
        item = stored.get(key)
        is_applied = bool(item and item.applied)
        applied += is_applied
        rows.append(
            {
                "key": key,
                "phase": phase,
                "label": label,
                "applied": is_applied,
                "notes": item.notes if item else "",
                "threat": threat,
            }
        )
    total = len(CATALOGS[catalog])
    return {"catalog": catalog, "applied": applied, "total": total, "ratio": applied / total, "items": rows}


def set_checklist_item(*, review, key, applied, notes=None):
    """Mark an item of a checklist (found by its key) as applied or not, with its notes; returns that checklist."""
    if key not in CHECKLIST_KEYS:
        raise_unknown_key(key)
    catalog = _catalog_of(key)
    if catalog == RAPID:
        rapid.require_rapid(review)
    kind = RAPID_ITEM if catalog == RAPID else CHECKLIST_ITEM
    defaults = {"applied": bool(applied)}
    if notes is not None:
        defaults["notes"] = check_length(notes, 500, field="notes")
    item = review.checklist_items.filter(key=key).first() or ProcessChecklistItem(review=review, key=key)
    tracker = kind.track(item)
    for name, value in defaults.items():
        setattr(item, name, value)
    item.save()
    kind.changed(review, tracker, name=CHECKLIST_LABELS[key])
    return checklist(review, catalog)


def raise_unknown_key(key):
    raise ValidationError(f"Unknown checklist action {key!r}.", field="key")
