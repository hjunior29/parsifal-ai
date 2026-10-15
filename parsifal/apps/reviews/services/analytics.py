"""Counts behind the Data Analysis page."""

from django.db.models import Count

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
