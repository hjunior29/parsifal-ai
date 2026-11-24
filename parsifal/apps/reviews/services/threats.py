"""
Threats to validity: each threat to the validity of the review, of a type, with its description and what was done to
mitigate it. Nothing about them is fixed: the types suggested follow Petersen et al. (2015) §3.6 (after Petersen &
Gencel 2013) and Wohlin et al. (2012), and a review may use any other. Kitchenham & Charters (2007) §7 asks the report
to discuss the strengths and weaknesses of the review; Petersen et al. (2015) §5.1.5 lists common threats.
"""

from django.db import transaction

from parsifal.apps.reviews.models import ReviewEvent, ValidityThreat
from parsifal.apps.reviews.services import history
from parsifal.apps.reviews.services._common import check_length, get_child, require

# The types suggested when a threat is written; any other is accepted.
SUGGESTED_TYPES = (
    # Petersen et al. (2015) §3.6, after Petersen & Gencel (2013)
    "Descriptive validity",
    "Theoretical validity",
    "Generalizability",
    "Interpretive validity",
    "Repeatability",
    # Wohlin et al. (2012), Experimentation in Software Engineering
    "Construct validity",
    "Internal validity",
    "External validity",
    "Conclusion validity",
)

# Examples of threats to a secondary study, from Petersen et al. (2015) §5.1.5 (with their type).
EXAMPLES = (
    ("Publication bias: negative, new or controversial views may not be published", "Theoretical validity"),
    ("Poorly designed data extraction forms and recording of the data", "Descriptive validity"),
    ("Researcher bias in the selection of the studies and the reporting of the data", "Theoretical validity"),
    ("The quality of the sample of studies with respect to the targeted population", "Theoretical validity"),
    ("Generalizability of the results, within the population and to others", "Generalizability"),
    ("Reliability of the conclusions drawn from the data, e.g. bias in its interpretation", "Interpretive validity"),
)

FIELDS = ("title", "category", "description", "mitigation")
LIMITS = {"title": 255, "category": 100}

# What the History records of the threats.
THREAT = history.Kind(
    "threat to validity",
    ReviewEvent.REPORTING,
    FIELDS,
    plural="threats to validity",
    labels=(("title", "Name"), ("category", "Type")),
)


def list_threats(review):
    return review.threats.all()


def grouped(review):
    """The review's threats by type, in the order of their first threat: [(type, [threats])]; untyped ones last."""
    groups = {}
    for threat in list_threats(review):
        groups.setdefault(threat.category, []).append(threat)
    untyped = groups.pop("", None)
    return list(groups.items()) + ([("", untyped)] if untyped else [])


def _clean(field, value):
    value = (value or "").strip()
    if field in LIMITS:
        check_length(value, LIMITS[field], field=field)
    return value


def _get(review, threat_id):
    return get_child(review.threats, threat_id, label="Threat")


@transaction.atomic
def add_threat(*, review, title, category="", description="", mitigation=""):
    require(title, field="title")
    threat = ValidityThreat.objects.create(
        review=review,
        title=_clean("title", title),
        category=_clean("category", category),
        description=_clean("description", description),
        mitigation=_clean("mitigation", mitigation),
        order=review.threats.count(),
    )
    THREAT.added(review, threat)
    return threat


@transaction.atomic
def update_threat(*, review, threat_id, **fields):
    """Change the fields given (``title``, ``category``, ``description``, ``mitigation``); the others stay."""
    threat = _get(review, threat_id)
    tracker = THREAT.track(threat)
    for field in FIELDS:
        value = fields.get(field)
        if value is None:
            continue
        if field == "title":
            require(value, field="title")
        setattr(threat, field, _clean(field, value))
    threat.save()
    THREAT.changed(review, tracker)
    return threat


def remove_threat(*, review, threat_id):
    threat = _get(review, threat_id)
    THREAT.removed(review, threat)
    threat.delete()
