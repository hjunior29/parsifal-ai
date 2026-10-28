"""Counts behind the Data Analysis page."""

from collections import Counter

from django.db.models import Count, Q

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import (
    Article,
    DataExtraction,
    DataExtractionField,
    QualityAssessment,
    ReviewAgent,
    SearchSession,
    SelectionCriteria,
    StudyDecision,
)
from parsifal.apps.reviews.services import quality
from parsifal.apps.reviews.services._common import get_child


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


# PRISMA 2020 flow diagram -------------------------------------------------------------------------------------------

OTHER_METHODS = {  # how a search session that is not a database search appears in "other methods"
    SearchSession.SNOWBALLING: "Citation searching",
    SearchSession.MANUAL: "Hand searching",
    SearchSession.OTHER: "Other methods",
}
NO_REASON = "No reason given"


def _eligibility(studies, full_text, not_retrieved, *, screened):
    """
    The PRISMA boxes of a column of studies (none duplicated). With ``screened`` (databases and registers), studies
    rejected without a full-text decision were excluded at the screening of titles and abstracts; in "other methods"
    there is no such screening and every rejection is a report excluded.
    """
    boxes = {
        "excluded": 0,
        "excluded_by_people": 0,
        "excluded_by_automation": 0,
        "not_retrieved": 0,
        "reasons": Counter(),
        "included": 0,
        "awaiting_screening": 0,
        "awaiting_full_text": 0,
    }
    for study in studies:
        decided = study["id"] in full_text
        if study["status"] == Article.UNCLASSIFIED and not decided:
            boxes["awaiting_screening"] += 1
        elif study["status"] == Article.REJECTED and not decided and screened:
            boxes["excluded"] += 1
            boxes["excluded_by_automation" if study["by_agent"] else "excluded_by_people"] += 1
        elif study["status"] == Article.REJECTED:
            reason = study["criteria"] or full_text.get(study["id"])
            if not_retrieved is not None and reason == not_retrieved:
                boxes["not_retrieved"] += 1
            else:
                boxes["reasons"][reason] += 1
        elif study["status"] == Article.ACCEPTED and decided:
            boxes["included"] += 1
        else:  # accepted at the screening, or decided at the full text but unclassified since
            boxes["awaiting_full_text"] += 1
    excluded_reports = sum(boxes["reasons"].values())
    boxes["assessed"] = excluded_reports + boxes["included"]
    boxes["sought"] = boxes["assessed"] + boxes["not_retrieved"] + boxes["awaiting_full_text"]
    return boxes


def _reasons(counter, descriptions):
    rows = [{"reason": descriptions.get(pk, NO_REASON), "studies": count} for pk, count in counter.items()]
    return sorted(rows, key=lambda row: (-row["studies"], row["reason"] == NO_REASON, row["reason"]))


def prisma(review):
    """
    The numbers of the PRISMA 2020 flow diagram, from the studies' statuses and the stage of the reviewers' decisions
    (title and abstract, full text: the Reviewers tab, as the PRISMA notes ask).

    - Records identified: the studies imported from each source; a source whose search session is snowballing,
      manual or other goes to "other methods", the others to databases and registers.
    - Records removed before screening: the duplicates.
    - Records excluded: rejected without a full-text decision, split by people and automation tools (note b of the
      diagram): automation when only AI agents rejected it at the screening (no person decided it there).
    - Reports sought: the studies past the screening (with a full-text decision, or accepted and waiting for one);
      not retrieved: rejected at the full text with the review's "not retrieved" criterion; excluded with reasons:
      rejected at the full text, by criterion (the study's, else its full-text decision's).
    - Studies included: accepted at the full text. Quality is assessed on the included studies (PRISMA item 18), so
      the quality cutoff is no box of the flow.
    - Awaiting: studies still unclassified, and accepted at the screening without a full-text decision yet.
    """
    agents = set(ReviewAgent.objects.filter(review=review).values_list("user_id", flat=True))
    rejected_by_agents, decided_by_people = set(), set()
    for article_id, user_id, status in StudyDecision.objects.filter(
        review=review, stage=StudyDecision.TITLE_ABSTRACT
    ).values_list("article_id", "user_id", "status"):
        if user_id not in agents:
            decided_by_people.add(article_id)
        elif status == Article.REJECTED:
            rejected_by_agents.add(article_id)
    full_text = {}  # study with a full-text decision → the criterion of a rejection there (None: none)
    for article_id, status, criteria_id in (
        StudyDecision.objects.filter(review=review, stage=StudyDecision.FULL_TEXT)
        .order_by("decided_at")
        .values_list("article_id", "status", "selection_criteria_id")
    ):
        if full_text.get(article_id) is None:
            full_text[article_id] = criteria_id if status == Article.REJECTED else None
    methods = dict(
        review.searchsession_set.exclude(source=None)
        .exclude(search_type=SearchSession.DATABASE)
        .values_list("source_id", "search_type")
    )
    sources = dict(review.sources.values_list("pk", "name"))
    databases, other = Counter(), Counter()
    database_studies, other_studies, duplicates = [], [], 0
    for article_id, source_id, status, criteria_id in review.article_set.values_list(
        "pk", "source_id", "status", "selection_criteria_id"
    ):
        by_agent = article_id in rejected_by_agents and article_id not in decided_by_people
        study = {"id": article_id, "status": status, "criteria": criteria_id, "by_agent": by_agent}
        if source_id in methods:
            other[OTHER_METHODS[methods[source_id]]] += 1
            if status != Article.DUPLICATED:
                other_studies.append(study)
            continue
        databases[sources.get(source_id) or "Other"] += 1
        if status == Article.DUPLICATED:
            duplicates += 1
        else:
            database_studies.append(study)
    not_retrieved = review.prisma_not_retrieved_id
    descriptions = dict(review.selectioncriteria_set.values_list("pk", "description"))
    main = _eligibility(database_studies, full_text, not_retrieved, screened=True)
    result = {
        "databases": [{"source": name, "records": count} for name, count in sorted(databases.items())],
        "records": sum(databases.values()),
        "duplicates": duplicates,
        "screened": len(database_studies),
        "excluded": main["excluded"],
        "excluded_by_people": main["excluded_by_people"],
        "excluded_by_automation": main["excluded_by_automation"],
        "sought": main["sought"],
        "not_retrieved": main["not_retrieved"],
        "assessed": main["assessed"],
        "excluded_reports": _reasons(main["reasons"], descriptions),
        "other_methods": None,
        "included": main["included"],
        "awaiting_screening": main["awaiting_screening"],
        "awaiting_full_text": main["awaiting_full_text"],
        "not_retrieved_criteria_id": not_retrieved,
    }
    if other:
        extra = _eligibility(other_studies, full_text, not_retrieved, screened=False)
        result["other_methods"] = {
            "methods": [{"method": name, "records": count} for name, count in sorted(other.items())],
            "records": sum(other.values()),
            "sought": extra["sought"],
            "not_retrieved": extra["not_retrieved"],
            "assessed": extra["assessed"],
            "excluded_reports": _reasons(extra["reasons"], descriptions),
            "included": extra["included"],
        }
        result["included"] += extra["included"]
        result["awaiting_screening"] += extra["awaiting_screening"]
        result["awaiting_full_text"] += extra["awaiting_full_text"]
    return result


def set_prisma_not_retrieved(*, review, criteria_id):
    """
    The exclusion criterion that means "full text not retrieved" in the PRISMA diagram (None or 0: none, and the box
    "Reports not retrieved" is left out).
    """
    if criteria_id in (None, 0, "", "0"):
        criteria = None
    else:
        criteria = get_child(review.selectioncriteria_set, criteria_id, label="Selection criteria")
        if criteria.criteria_type != SelectionCriteria.EXCLUSION:
            raise ValidationError("Choose an exclusion criterion.", field="criteria_id")
    review.prisma_not_retrieved = criteria
    review.save(update_fields=["prisma_not_retrieved"])
    return review
