"""Counts behind the Data Analysis page."""

from collections import Counter

from django.db.models import Count, Q

from parsifal.apps.reviews.models import Article


def selection_by_source(review):
    """Per source: how many articles were imported and how many are accepted."""
    rows = []
    for source in review.sources.all():
        articles = review.article_set.filter(source=source)
        rows.append(
            {
                "source_id": source.pk,
                "source": source.name,
                "total": articles.count(),
                "accepted": articles.filter(status=Article.ACCEPTED).count(),
            }
        )
    return rows


def final_selection_by_year(review):
    """Final-selection articles per publication year, most recent first; unknown years are reported as None."""
    counts = review.get_final_selection_articles().values("year_int").annotate(count=Count("id")).order_by("-year_int")
    return [{"year": row["year_int"], "count": row["count"]} for row in counts]


def _share(part, whole):
    return round(part / whole, 4) if whole else None


def selection_summary(review):
    """
    The study selection in numbers: the studies per status, the duplicates against every study imported, the
    accepted, rejected and still unclassified ones against the studies that are not duplicates, the final selection
    (accepted, and above the quality cutoff when there is one), and the statuses per source.
    """
    counts = Counter(review.article_set.values_list("status", flat=True))
    total = sum(counts.values())
    duplicated = counts[Article.DUPLICATED]
    unique = total - duplicated
    accepted, rejected = counts[Article.ACCEPTED], counts[Article.REJECTED]
    unclassified = counts[Article.UNCLASSIFIED]
    by_source = []
    for source in review.sources.order_by("name"):
        per_status = Counter(review.article_set.filter(source=source).values_list("status", flat=True))
        by_source.append(
            {
                "source_id": source.pk,
                "source": source.name,
                "total": sum(per_status.values()),
                **{name: per_status[code] for code, name in STATUS_NAMES.items()},
            }
        )
    return {
        "total": total,
        "duplicated": duplicated,
        "unique": unique,
        "accepted": accepted,
        "rejected": rejected,
        "unclassified": unclassified,
        "final": review.get_final_selection_articles().count(),
        "duplicated_share": _share(duplicated, total),  # of every study imported
        "accepted_share": _share(accepted, unique),  # of the studies that are not duplicates
        "rejected_share": _share(rejected, unique),
        "unclassified_share": _share(unclassified, unique),
        "by_source": by_source,
    }


STATUS_NAMES = {
    Article.ACCEPTED: "accepted",
    Article.REJECTED: "rejected",
    Article.UNCLASSIFIED: "unclassified",
    Article.DUPLICATED: "duplicated",
}


def criteria_usage(review):
    """
    How often each criterion is the reason of a study's status, most used first: each exclusion criterion by the
    rejected studies that have it, each inclusion criterion by the accepted ones; and how many rejected and accepted
    studies have no criterion.
    """

    def ranked(criteria, status, prefix):
        rows = [
            {
                "id": criterion.pk,
                "key": f"{prefix}{index}",
                "description": criterion.description,
                "studies": criterion.studies,
            }
            for index, criterion in enumerate(
                criteria.annotate(studies=Count("article", filter=Q(article__status=status))), start=1
            )
        ]
        return sorted(rows, key=lambda row: (-row["studies"], row["key"]))

    articles = review.article_set
    return {
        "exclusion": ranked(review.get_exclusion_criterias(), Article.REJECTED, "E"),
        "inclusion": ranked(review.get_inclusion_criterias(), Article.ACCEPTED, "I"),
        "rejected_without_criterion": articles.filter(status=Article.REJECTED, selection_criteria=None).count(),
        "accepted_without_criterion": articles.filter(status=Article.ACCEPTED, selection_criteria=None).count(),
    }


def studies_by_year(review):
    """
    The studies that are not duplicates per publication year and status, oldest first; a study without a year is
    counted under None, last.
    """
    rows = (
        review.article_set.exclude(status=Article.DUPLICATED)
        .values("year_int", "status")
        .annotate(count=Count("pk"))
        .order_by()
    )
    years = {}
    for row in rows:
        year = years.setdefault(
            row["year_int"], {"year": row["year_int"], "accepted": 0, "rejected": 0, "unclassified": 0}
        )
        year[STATUS_NAMES[row["status"]]] = row["count"]
    return sorted(years.values(), key=lambda row: (row["year"] is None, row["year"] or 0))
