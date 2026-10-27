"""Counts behind the Data Analysis page."""

from collections import Counter

from django.db.models import Count, Q

from parsifal.apps.reviews.models import Article, DataExtraction, DataExtractionField, QualityAssessment
from parsifal.apps.reviews.services import quality


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


def quality_overview(review):
    """
    Quality assessment in numbers, over the accepted studies: how many are assessed (every question answered),
    partly assessed or not yet; with a cutoff, how many are above it and how many at most; how many fully assessed
    studies have each score; and how many studies have each answer to each question (and none).
    """
    questions = list(review.qualityquestion_set.all())
    answers = list(review.qualityanswer_set.all())  # the highest weight first
    rows = list(quality.assessment_list(review).values("score", "answered"))
    count = len(questions)
    assessed = sum(1 for row in rows if count and row["answered"] >= count)
    partly = sum(1 for row in rows if 0 < row["answered"] < count)
    cutoff = review.quality_assessment_cutoff_score
    has_cutoff = review.has_quality_assessment_checklist() and cutoff > 0
    above = sum(1 for row in rows if row["score"] > cutoff) if has_cutoff else None
    scores = Counter(round(row["score"], 2) for row in rows if count and row["answered"] >= count)
    chosen = Counter(
        {
            (row["question_id"], row["answer_id"]): row["studies"]
            for row in QualityAssessment.objects.filter(
                article__review=review, article__status=Article.ACCEPTED, answer__isnull=False
            )
            .values("question_id", "answer_id")
            .annotate(studies=Count("pk"))
            .order_by()
        }
    )
    by_question = []
    for index, question in enumerate(questions, start=1):
        per_answer = [{"answer_id": answer.pk, "studies": chosen[(question.pk, answer.pk)]} for answer in answers]
        by_question.append(
            {
                "id": question.pk,
                "key": f"Q{index}",
                "description": question.description,
                "answers": per_answer,
                "unanswered": len(rows) - sum(row["studies"] for row in per_answer),
            }
        )
    return {
        "accepted": len(rows),
        "questions": count,
        "assessed": assessed,
        "partly": partly,
        "not_assessed": len(rows) - assessed - partly,
        "cutoff": cutoff if has_cutoff else None,
        "above_cutoff": above,
        "at_most_cutoff": len(rows) - above if has_cutoff else None,
        "max_score": quality.max_score(review),
        "scores": [{"score": score, "studies": studies} for score, studies in sorted(scores.items())],
        "answers": [{"id": a.pk, "description": a.description, "weight": a.weight} for a in answers],
        "by_question": by_question,
    }


# The fields Data Analysis draws: those whose answers are options to choose (text, numbers and dates are left out).
CHOICE_FIELDS = (
    DataExtractionField.SELECT_ONE_FIELD,
    DataExtractionField.SELECT_MANY_FIELD,
    DataExtractionField.BOOLEAN_FIELD,
)


def extraction_choices(review):
    """
    How often each option of the choice fields (single choice, multiple choice, true/false) was chosen for the
    studies of the final selection, in the form's order: each option with its studies, the most chosen first (true
    before false), and how many studies have an answer and how many have none. A study may have several options of a
    multiple choice field. Also how many studies are in the final selection and how many are marked as done.
    """
    studies = review.get_final_selection_articles()
    ids = list(studies.values_list("pk", flat=True))
    fields = review.dataextractionfield_set.filter(field_type__in=CHOICE_FIELDS).prefetch_related(
        "dataextractionlookup_set"
    )
    rows = []
    for field in fields:
        extractions = DataExtraction.objects.filter(field=field, article_id__in=ids)
        if field.field_type == DataExtractionField.BOOLEAN_FIELD:
            counts = Counter(extractions.exclude(value="").values_list("value", flat=True))
            options = [{"id": None, "value": value, "studies": counts[value]} for value in ("True", "False")]
            answered = sum(option["studies"] for option in options)
        else:
            chosen = extractions.filter(select_values__isnull=False)
            counts = dict(
                chosen.values_list("select_values").annotate(studies=Count("article", distinct=True)).order_by()
            )
            options = sorted(
                (
                    {"id": lookup.pk, "value": lookup.value, "studies": counts.get(lookup.pk, 0)}
                    for lookup in field.dataextractionlookup_set.all()
                ),
                key=lambda option: -option["studies"],
            )
            answered = chosen.values("article").distinct().count()
        rows.append(
            {
                "id": field.pk,
                "description": field.description,
                "field_type": field.field_type,
                "answered": answered,
                "unanswered": len(ids) - answered,
                "options": options,
            }
        )
    return {
        "studies": len(ids),
        "done": studies.filter(finished_data_extraction=True).count(),
        "fields": rows,
    }
