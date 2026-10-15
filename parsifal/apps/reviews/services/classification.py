"""
Classification schemes for systematic mapping studies (Petersen et al. 2015 §5.1.3): facets with categories,
per-article classifications, and the frequency/matrix aggregations behind bubble plots.
"""

from collections import Counter

from django.db import transaction
from django.db.models import Count

from parsifal.apps.core.exceptions import Conflict, ValidationError
from parsifal.apps.reviews.models import ArticleClassification, ClassificationCategory, ClassificationFacet
from parsifal.apps.reviews.services._common import check_length, get_child, get_children, reorder, require

# Topic-independent facets recommended by the guidelines (Wieringa et al. research types; Petersen 2008/2015).
FACET_TEMPLATES = {
    "research_type": {
        "name": "Research type",
        "description": "Wieringa et al. (2006) research type facet.",
        "multiple": False,
        "categories": (
            ("Evaluation research", "Techniques implemented in practice and evaluated (benefits and drawbacks)."),
            ("Validation research", "Novel techniques investigated in the lab (experiments, prototyping...)."),
            ("Solution proposal", "A solution is proposed and argued for, without full-blown validation."),
            ("Philosophical paper", "A new way of looking at things; a conceptual framework or taxonomy."),
            ("Experience paper", "What and how something has been done in practice; the author's experience."),
            ("Opinion paper", "Personal opinion on whether a technique is good or bad; no research method."),
        ),
    },
    "contribution_type": {
        "name": "Contribution type",
        "description": "Type of intervention studied (Petersen et al. 2008).",
        "multiple": True,
        "categories": (("Process", ""), ("Method", ""), ("Model", ""), ("Tool", ""), ("Metric", ""), ("Other", "")),
    },
    "research_method": {
        "name": "Research method",
        "description": "Empirical method used by the study.",
        "multiple": True,
        "categories": (
            ("Case study", ""),
            ("Experiment", ""),
            ("Survey", ""),
            ("Action research", ""),
            ("Grounded theory", ""),
            ("Design science", ""),
            ("Literature review", ""),
            ("Other / none", ""),
        ),
    },
    "venue_type": {
        "name": "Venue type",
        "description": "Publication venue.",
        "multiple": False,
        "categories": (
            ("Journal", ""),
            ("Conference", ""),
            ("Workshop", ""),
            ("Book chapter", ""),
            ("Thesis", ""),
            ("Technical report", ""),
            ("Other", ""),
        ),
    },
    "study_focus": {
        "name": "Study focus",
        "description": "Context in which the study was carried out.",
        "multiple": True,
        "categories": (("Academic", ""), ("Industrial", ""), ("Government", ""), ("Open source", ""), ("Other", "")),
    },
}


def list_templates():
    return [
        {
            "key": key,
            "name": spec["name"],
            "description": spec["description"],
            "multiple": spec["multiple"],
            "categories": [name for name, _description in spec["categories"]],
        }
        for key, spec in FACET_TEMPLATES.items()
    ]


# ---------------------------------------------------------------------------------------------------------------------
# Facets and categories
# ---------------------------------------------------------------------------------------------------------------------


def _validate_kind(kind):
    if kind not in dict(ClassificationFacet.KINDS):
        raise ValidationError("kind must be 'fixed' or 'emerging'.", field="kind")
    return kind


@transaction.atomic
def add_facet(*, review, name, kind=ClassificationFacet.EMERGING, description="", multiple=False, categories=()):
    require(name, field="name")
    check_length(name, 100, field="name")
    check_length(description or "", 500, field="description")
    if review.facets.filter(name__iexact=name).exists():
        raise Conflict(f"A facet named {name!r} already exists in this review.", field="name")
    facet = ClassificationFacet.objects.create(
        review=review,
        name=name,
        kind=_validate_kind(kind),
        description=description or "",
        multiple=bool(multiple),
        order=review.facets.count(),
    )
    for category in categories:
        add_category(review=review, facet_id=facet.pk, name=category)
    return facet


@transaction.atomic
def add_facet_from_template(*, review, template):
    if template not in FACET_TEMPLATES:
        raise ValidationError(f"Unknown template {template!r}; see list_templates().", field="template")
    spec = FACET_TEMPLATES[template]
    facet = add_facet(
        review=review,
        name=spec["name"],
        kind=ClassificationFacet.FIXED,
        description=spec["description"],
        multiple=spec["multiple"],
    )
    facet.template = template
    facet.save(update_fields=["template"])
    for position, (name, description) in enumerate(spec["categories"]):
        ClassificationCategory.objects.create(facet=facet, name=name, description=description, order=position)
    return facet


def update_facet(*, review, facet_id, name=None, description=None, kind=None, multiple=None):
    facet = get_child(review.facets, facet_id, label="Facet")
    if name is not None:
        require(name, field="name")
        check_length(name, 100, field="name")
        if review.facets.exclude(pk=facet.pk).filter(name__iexact=name).exists():
            raise Conflict(f"A facet named {name!r} already exists in this review.", field="name")
        facet.name = name
    if description is not None:
        facet.description = check_length(description, 500, field="description")
    if kind is not None:
        facet.kind = _validate_kind(kind)
    if multiple is not None:
        if not multiple and facet.multiple:
            # A single-choice facet cannot hold several categories for one article.
            duplicated = (
                ArticleClassification.objects.filter(facet=facet)
                .values("article")
                .annotate(total=Count("id"))
                .filter(total__gt=1)
            )
            if duplicated.exists():
                raise Conflict("Some articles have several categories in this facet; cannot make it single-choice.")
        facet.multiple = bool(multiple)
    facet.save()
    return facet


def remove_facet(*, review, facet_id):
    get_child(review.facets, facet_id, label="Facet").delete()


def reorder_facets(*, review, ordered_ids):
    return reorder(review.facets, ordered_ids, label="Facet")


def add_category(*, review, facet_id, name, description=""):
    facet = get_child(review.facets, facet_id, label="Facet")
    require(name, field="name")
    check_length(name, 200, field="name")
    check_length(description or "", 500, field="description")
    if facet.categories.filter(name__iexact=name).exists():
        raise Conflict(f"Category {name!r} already exists in facet {facet.name!r}.", field="name")
    return ClassificationCategory.objects.create(
        facet=facet, name=name, description=description or "", order=facet.categories.count()
    )


def update_category(*, review, facet_id, category_id, name=None, description=None):
    facet = get_child(review.facets, facet_id, label="Facet")
    category = get_child(facet.categories, category_id, label="Category")
    if name is not None:
        require(name, field="name")
        check_length(name, 200, field="name")
        if facet.categories.exclude(pk=category.pk).filter(name__iexact=name).exists():
            raise Conflict(f"Category {name!r} already exists in facet {facet.name!r}.", field="name")
        category.name = name
    if description is not None:
        category.description = check_length(description, 500, field="description")
    category.save()
    return category


def remove_category(*, review, facet_id, category_id):
    facet = get_child(review.facets, facet_id, label="Facet")
    get_child(facet.categories, category_id, label="Category").delete()


def reorder_categories(*, review, facet_id, ordered_ids):
    facet = get_child(review.facets, facet_id, label="Facet")
    return reorder(facet.categories, ordered_ids, label="Category")


# ---------------------------------------------------------------------------------------------------------------------
# Classifying articles
# ---------------------------------------------------------------------------------------------------------------------


@transaction.atomic
def classify(*, review, article_id, facet_id, category_ids, actor=None, notes=""):
    """
    Set the categories of ``facet`` for ``article`` (set semantics). Single-choice facets accept at most one
    category; an empty list clears the classification.
    """
    article = get_child(review.article_set, article_id, label="Article")
    facet = get_child(review.facets, facet_id, label="Facet")
    category_ids = list(dict.fromkeys(category_ids or []))
    if not facet.multiple and len(category_ids) > 1:
        raise ValidationError(f"Facet {facet.name!r} accepts a single category.", field="category_ids")
    categories = get_children(facet.categories, category_ids, label="Category")
    check_length(notes or "", 2000, field="notes")
    ArticleClassification.objects.filter(article=article, facet=facet).exclude(category__in=categories).delete()
    for category in categories:
        ArticleClassification.objects.update_or_create(
            article=article, facet=facet, category=category, defaults={"user": actor, "notes": notes or ""}
        )
    return article_classifications(review=review, article_id=article.pk)


def article_classifications(*, review, article_id):
    """One row per facet of the review with the categories assigned to the article."""
    article = get_child(review.article_set, article_id, label="Article")
    assigned = {}
    for row in article.classifications.select_related("category", "user"):
        assigned.setdefault(row.facet_id, []).append(row)
    result = []
    for facet in review.facets.prefetch_related("categories"):
        rows = assigned.get(facet.pk, [])
        result.append(
            {
                "facet": facet,
                "categories": [row.category for row in rows],
                "notes": rows[0].notes if rows else "",
                "user": rows[0].user if rows else None,
            }
        )
    return result


def classified_articles(review):
    """Articles that a mapping study classifies: the final selection (accepted, cut-off applied when present)."""
    return review.get_final_selection_articles()


def facet_frequencies(*, review, facet_id):
    facet = get_child(review.facets, facet_id, label="Facet")
    articles = classified_articles(review)
    counts = Counter(
        ArticleClassification.objects.filter(facet=facet, article__in=articles).values_list("category_id", flat=True)
    )
    classified = (
        ArticleClassification.objects.filter(facet=facet, article__in=articles).values("article").distinct().count()
    )
    return {
        "facet_id": facet.pk,
        "facet": facet.name,
        "total_articles": articles.count(),
        "classified_articles": classified,
        "categories": [
            {"category_id": category.pk, "category": category.name, "count": counts.get(category.pk, 0)}
            for category in facet.categories.all()
        ],
    }


def facet_matrix(*, review, row_facet_id, column_facet_id):
    """Counts of articles per (row category, column category) — the data behind a bubble plot."""
    rows_facet = get_child(review.facets, row_facet_id, label="Facet")
    columns_facet = get_child(review.facets, column_facet_id, label="Facet")
    articles = classified_articles(review)
    by_article_rows, by_article_columns = {}, {}
    for row in ArticleClassification.objects.filter(facet=rows_facet, article__in=articles):
        by_article_rows.setdefault(row.article_id, set()).add(row.category_id)
    for row in ArticleClassification.objects.filter(facet=columns_facet, article__in=articles):
        by_article_columns.setdefault(row.article_id, set()).add(row.category_id)
    cells = Counter()
    for article_id, row_categories in by_article_rows.items():
        for column_category in by_article_columns.get(article_id, ()):
            for row_category in row_categories:
                cells[(row_category, column_category)] += 1
    rows = list(rows_facet.categories.all())
    columns = list(columns_facet.categories.all())
    return {
        "rows": {"facet_id": rows_facet.pk, "facet": rows_facet.name, "categories": [c.name for c in rows]},
        "columns": {
            "facet_id": columns_facet.pk,
            "facet": columns_facet.name,
            "categories": [c.name for c in columns],
        },
        "cells": [
            {"row": r.name, "column": c.name, "count": cells.get((r.pk, c.pk), 0)} for r in rows for c in columns
        ],
    }
