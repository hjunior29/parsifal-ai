"""
What is specific to a rapid review (Cartaxo, Pinto & Soares 2020, "Rapid Reviews in Software Engineering"): its
checklist of the collaboration with practitioners and of the concessions made to be rapid, each with its
justification, and the threats to validity drafted from those concessions. A rapid review is not an ad-hoc review:
every concession is documented in its protocol ([G] §2.1, §4.2). The concessions are a menu, not a package: the
checklist records which were made and why, it enforces none.
"""

from django.db import transaction

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import ReviewEvent, ValidityThreat
from parsifal.apps.reviews.services import history

THEORETICAL, GENERALIZABILITY = "Theoretical validity", "Generalizability"
INTERPRETIVE, DESCRIPTIVE = "Interpretive validity", "Descriptive validity"

# (key, group, label, the type of the threat it brings, the threat) — a concession has a threat; an item of the
# collaboration with practitioners, or one that mitigates a concession, has none.
RAPID_CHECKLIST = (
    # Collaboration with practitioners ([G] §4.1; [E] §3–4)
    ("rr_problem_with_practitioners", "Collaboration", "Problem defined with the practitioners", "", ""),
    ("rr_questions_with_practitioners", "Collaboration", "Research questions defined with the practitioners", "", ""),
    ("rr_protocol_validated", "Collaboration", "Protocol validated with the practitioners", "", ""),
    ("rr_search_refined", "Collaboration", "Search string refined with the practitioners", "", ""),
    ("rr_doubtful_studies_shown", "Collaboration", "Doubtful studies shown to the practitioners", "", ""),
    ("rr_findings_workshop", "Collaboration", "Findings discussed with the practitioners in a workshop", "", ""),
    ("rr_adoption_follow_up", "Collaboration", "Follow-up on the adoption of the findings", "", ""),
    # Search ([G] §4.2.1)
    (
        "rr_single_source",
        "Search",
        "A single search source",
        THEORETICAL,
        "Only one search source was used, which may limit the primary studies found.",
    ),
    ("rr_snowballing", "Search", "Snowballing to complement the source", "", ""),
    (
        "rr_limit_date",
        "Search",
        "Search limited by date",
        THEORETICAL,
        "Studies published outside the period searched were left out.",
    ),
    (
        "rr_limit_language",
        "Search",
        "Search limited by language",
        THEORETICAL,
        "Studies written in other languages were left out.",
    ),
    (
        "rr_limit_geography",
        "Search",
        "Search limited by geographical area",
        GENERALIZABILITY,
        "Studies from other geographical areas were left out, which limits the generalization of the findings.",
    ),
    (
        "rr_limit_method",
        "Search",
        "Search limited by research method",
        THEORETICAL,
        "Studies that used other research methods were left out.",
    ),
    (
        "rr_peer_reviewed_only",
        "Search",
        "Peer-reviewed literature only",
        THEORETICAL,
        "Grey literature was left out, which may increase publication bias.",
    ),
    # Selection ([G] §4.2.2)
    (
        "rr_one_reviewer",
        "Selection",
        "Studies selected by one reviewer",
        THEORETICAL,
        "A single reviewer selected the studies, which may introduce selection bias.",
    ),
    ("rr_second_reviewer_sample", "Selection", "A second reviewer on a sample of the studies", "", ""),
    (
        "rr_context_criteria",
        "Selection",
        "Selection criteria restricted to the practical context",
        GENERALIZABILITY,
        "Criteria restricted to the practical context make the evidence contextual: the findings may not apply to "
        "other contexts.",
    ),
    (
        "rr_title_round",
        "Selection",
        "A first round on the titles only",
        THEORETICAL,
        "Relevant studies may have been lost because of their titles.",
    ),
    # Quality appraisal ([G] §4.2.3)
    (
        "rr_no_quality",
        "Quality appraisal",
        "Quality of the studies not appraised",
        INTERPRETIVE,
        "The quality of the studies was not appraised, which may limit the reliability of the evidence.",
    ),
    (
        "rr_rigorous_venues",
        "Quality appraisal",
        "Only venues with a rigorous review process",
        THEORETICAL,
        "Only studies from venues with a rigorous review process were considered, which may leave relevant studies "
        "out.",
    ),
    (
        "rr_one_appraiser",
        "Quality appraisal",
        "Quality appraised by one reviewer",
        INTERPRETIVE,
        "A single reviewer appraised the quality of the studies, which may bias the appraisal.",
    ),
    ("rr_pairs_sample", "Quality appraisal", "Quality appraised in pairs on a sample of the studies", "", ""),
    # Extraction ([G] §4.2.4)
    (
        "rr_one_extractor",
        "Extraction",
        "Data extracted by one reviewer",
        DESCRIPTIVE,
        "A single reviewer extracted the data, which may introduce bias in the extraction.",
    ),
    (
        "rr_missing_data_excluded",
        "Extraction",
        "Studies with missing data excluded, their authors not contacted",
        THEORETICAL,
        "Studies with missing data were excluded without contacting their authors: some evidence may be missing.",
    ),
    # Synthesis ([G] §4.2.5)
    (
        "rr_narrative_synthesis",
        "Synthesis",
        "A narrative synthesis instead of a formal method",
        INTERPRETIVE,
        "A narrative synthesis, instead of a formal method, may make the conclusions less reliable.",
    ),
    # Reporting ([G] §4.3, §5.2)
    ("rr_evidence_briefing", "Reporting", "An Evidence Briefing for the practitioners", "", ""),
    ("rr_protocol_available", "Reporting", "Protocol and list of the primary studies made available", "", ""),
    ("rr_scientific_venue", "Reporting", "Also reported in a scientific venue", "", ""),
)

RAPID_KEYS = {key for key, *_rest in RAPID_CHECKLIST}


def require_rapid(review):
    if not review.is_rapid_review:
        raise ValidationError("The rapid review checklist is only for rapid reviews.", field="catalog")


@transaction.atomic
def draft_threats(*, review, actor=None):
    """
    A threat to validity for each concession of the checklist applied that brings one: its name, type, the threat
    and, as its mitigation, the justification of the concession. Only appended: a concession whose threat the review
    has already (by name) is left alone, and nothing is overwritten. Returns the threats added.
    """
    require_rapid(review)
    applied = {item.key: item for item in review.checklist_items.filter(key__in=RAPID_KEYS, applied=True)}
    existing = {title.lower() for title in review.threats.values_list("title", flat=True)}
    order = review.threats.count()
    added = []
    for key, _group, label, category, threat in RAPID_CHECKLIST:
        if not threat or key not in applied or label.lower() in existing:
            continue
        added.append(
            ValidityThreat.objects.create(
                review=review,
                title=label,
                category=category,
                description=threat,
                mitigation=applied[key].notes,
                order=order + len(added),
            )
        )
    if added:
        history.record(
            review,
            ReviewEvent.REPORTING,
            history.ADDED,
            f"Drafted {history.plural(len(added), 'threat')} to validity from the concessions of the rapid review",
            subject="threat_to_validity",
            items=[threat.title for threat in added],
            actor=actor,
        )
    return added
