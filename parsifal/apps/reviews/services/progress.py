"""
How far a review has come, from its protocol to its manuscript, as one percentage and the steps behind it.

The three phases weigh as the work they take: Planning 20%, Conducting 70%, Reporting 10%. Inside a phase its steps
share its weight equally. A step of the protocol is done once it has something (at least one field of the PICOC,
one research question...): no review needs every field. A step over the studies counts in proportion (the studies
screened, assessed, extracted). Quality assessment is a step of systematic literature reviews; a mapping study or a
rapid review counts it only when it has a checklist. The review is complete once every study left has its data
extracted and a manuscript has a version.
"""

from dataclasses import asdict, dataclass

from django.db.models import Count, Q

from parsifal.apps.reviews.models import Article, ManuscriptVersion, Review
from parsifal.apps.reviews.services import quality

PLANNING, CONDUCTING, REPORTING = "planning", "conducting", "reporting"
PHASES = ((PLANNING, "Planning", 20), (CONDUCTING, "Conducting", 70), (REPORTING, "Reporting", 10))


@dataclass
class Step:
    key: str
    phase: str
    label: str
    done: float  # 0 to 1
    detail: str = ""
    page: str = ""  # the name of the web page where it is done


def _share(part, whole):
    return min(part / whole, 1.0) if whole else 0.0


def _studies(count):
    return f"{count} stud{'y' if count == 1 else 'ies'}"


def _count(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def _planning(review):
    picoc = [
        name for name in ("population", "intervention", "comparison", "outcome", "context") if getattr(review, name)
    ]
    has_string = bool(review.get_generic_search_string().search_string.strip()) or any(
        session.search_string.strip() for session in review.get_latest_source_search_strings()
    )
    criteria = review.selectioncriteria_set.aggregate(
        inclusion=Count("pk", filter=Q(criteria_type="I")), exclusion=Count("pk", filter=Q(criteria_type="E"))
    )
    fields, facets = review.dataextractionfield_set.count(), review.facets.count()
    steps = [
        Step("objective", PLANNING, "Objective", float(bool(review.objective.strip())), page="protocol"),
        Step("picoc", PLANNING, "PICOC (at least one)", float(bool(picoc)), ", ".join(picoc).title(), "protocol"),
        Step(
            "research_questions",
            PLANNING,
            "Research questions",
            float(review.research_questions.exists()),
            f"{review.research_questions.count()}",
            "protocol",
        ),
        Step("search_string", PLANNING, "Search string", float(has_string), page="protocol"),
        Step("sources", PLANNING, "Sources", float(review.sources.exists()), f"{review.sources.count()}", "protocol"),
        Step(
            "selection_criteria",
            PLANNING,
            "Selection criteria",
            float(bool(criteria["inclusion"] or criteria["exclusion"])),
            f"{criteria['inclusion']} inclusion, {criteria['exclusion']} exclusion",
            "protocol",
        ),
    ]
    if _quality_counts(review):
        steps.append(
            Step(
                "quality_checklist",
                PLANNING,
                "Quality assessment checklist",
                float(review.has_quality_assessment_checklist()),
                f"{_count(review.qualityquestion_set.count(), 'question')}, "
                f"{_count(review.qualityanswer_set.count(), 'answer')}",
                "quality_assessment_checklist",
            )
        )
    steps.append(
        Step(
            "extraction_form",
            PLANNING,
            "Data extraction form",
            float(bool(fields or facets)),
            _count(fields, "field") + (f", {_count(facets, 'facet')}" if facets else ""),
            "data_extraction_form",
        )
    )
    return steps


def _quality_counts(review):
    """Whether quality assessment is a step of the review: always in an SLR, otherwise only with a checklist."""
    return review.review_type == Review.SLR or review.has_quality_assessment_checklist()


def _conducting(review):
    counts = review.article_set.aggregate(
        total=Count("pk"),
        duplicated=Count("pk", filter=Q(status=Article.DUPLICATED)),
        decided=Count("pk", filter=Q(status__in=(Article.ACCEPTED, Article.REJECTED))),
        accepted=Count("pk", filter=Q(status=Article.ACCEPTED)),
    )
    screened = counts["total"] - counts["duplicated"]
    steps = [
        Step(
            "studies",
            CONDUCTING,
            "Studies imported",
            float(bool(counts["total"])),
            _studies(counts["total"]),
            "import_studies",
        ),
        Step(
            "selection",
            CONDUCTING,
            "Study selection",
            _share(counts["decided"], screened),
            f"{counts['decided']} of {_studies(screened)} accepted or rejected",
            "study_selection",
        ),
    ]
    if _quality_counts(review):
        questions = review.qualityquestion_set.count()
        rows = quality.assessment_list(review).values_list("answered", flat=True) if questions else []
        assessed = sum(1 for answered in rows if answered >= questions)
        steps.append(
            Step(
                "quality",
                CONDUCTING,
                "Quality assessment",
                _share(assessed, counts["accepted"]) if questions else 0.0,
                f"{assessed} of {_studies(counts['accepted'])} accepted assessed",
                "quality_assessment",
            )
        )
    final = review.get_final_selection_articles()
    selected, extracted = final.count(), final.filter(finished_data_extraction=True).count()
    steps.append(
        Step(
            "extraction",
            CONDUCTING,
            "Data extraction",
            _share(extracted, selected),
            f"{extracted} of {_studies(selected)} done",
            "data_extraction",
        )
    )
    return steps


def _reporting(review):
    threats = review.threats.count()
    versions = ManuscriptVersion.objects.filter(manuscript__review=review).count()
    return [
        Step(
            "threats",
            REPORTING,
            "Threats to validity",
            float(bool(threats)),
            f"{threats}",
            "threats_to_validity",
        ),
        Step(
            "manuscript",
            REPORTING,
            "Manuscript",
            float(bool(versions)),
            f"{_count(review.manuscripts.count(), 'manuscript')}, {_count(versions, 'version')}",
            "manuscripts",
        ),
    ]


def progress(review):
    """
    {"percent": 0–100, "phases": [{"key", "label", "weight", "percent", "steps": [{"key", "label", "done" (0–1),
    "detail", "page"}]}], "next": the first step not done, or None}. 100 only when every step is done.
    """
    steps = _planning(review) + _conducting(review) + _reporting(review)
    phases, total = [], 0.0
    for key, label, weight in PHASES:
        own = [step for step in steps if step.phase == key]
        share = sum(step.done for step in own) / len(own) if own else 1.0
        total += weight * share
        phases.append(
            {
                "key": key,
                "label": label,
                "weight": weight,
                "percent": int(share * 100),
                "steps": [asdict(step) for step in own],
            }
        )
    following = next((step for step in steps if step.done < 1), None)
    return {
        "percent": 100 if following is None else min(int(total), 99),
        "phases": phases,
        "next": asdict(following) if following else None,
    }
