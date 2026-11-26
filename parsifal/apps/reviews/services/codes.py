"""
The codes a review gives its research questions (RQ1, RQ2, RQ1.1 for a sub-question), its selection criteria (IC1…,
EC1…), its quality assessment questions (QA1…) and its data extraction fields (EX01…). They come from the order of
each list, so moving one renumbers the others, and nobody writes them in the names: ``written`` finds the codes typed
by hand at the start of a name, and ``strip_written`` removes them.

The prefixes are the review's (``Review.code_prefixes``): RQ, IC, EC, QA and EX unless it chose others — QP, CI, CE…
for a review written in Portuguese. A code has as many digits as the longest of its list (EX01…EX25, RQ1…RQ4).
"""

import re
from collections import defaultdict

from django.db import transaction

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import DataExtractionField, QualityQuestion, Question, ReviewEvent, SelectionCriteria
from parsifal.apps.reviews.services import history

QUESTION, INCLUSION, EXCLUSION, QUALITY, EXTRACTION = "question", "inclusion", "exclusion", "quality", "extraction"
DEFAULT_PREFIXES = {QUESTION: "RQ", INCLUSION: "IC", EXCLUSION: "EC", QUALITY: "QA", EXTRACTION: "EX"}
KINDS = (
    (QUESTION, "Research questions"),
    (INCLUSION, "Inclusion criteria"),
    (EXCLUSION, "Exclusion criteria"),
    (QUALITY, "Quality assessment questions"),
    (EXTRACTION, "Data extraction fields"),
)
PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,5}$")

# A code typed at the start of a name: "RQ1: ", "QL1 | ", "EX01 | ", "RQ1.1: ", "IC 2 - ".
WRITTEN = re.compile(r"^\s*([A-Z]{1,4})\s?-?(\d{1,3}(?:\.\d{1,3})*)\s*[:|.\-–—)]\s+")


def prefixes(review):
    """The review's prefixes, every kind: its own, else the default."""
    own = review.code_prefixes or {}
    return {kind: (own.get(kind) or default) for kind, default in DEFAULT_PREFIXES.items()}


def clean_prefixes(value, current=None):
    """
    The prefixes to keep, from {"question": "QP", …} or ["question=QP", …] (the CLI's way): every kind, each one to
    six letters or digits starting with a letter, all different. A kind left out keeps its prefix in ``current`` (the
    review's), else the default; one given empty goes back to the default.
    """
    if isinstance(value, (list, tuple)):
        pairs = {}
        for item in value:
            kind, sep, prefix = str(item).partition("=")
            if not sep:
                raise ValidationError(f"Give each prefix as kind=PREFIX, not {item!r}.", field="code_prefixes")
            pairs[kind.strip()] = prefix
        value = pairs
    if not isinstance(value, dict):
        raise ValidationError("code_prefixes must map each kind to its prefix.", field="code_prefixes")
    cleaned = {**DEFAULT_PREFIXES, **(current or {})}
    for kind, prefix in value.items():
        if kind not in DEFAULT_PREFIXES:
            raise ValidationError(f"Unknown kind {kind!r}: use {', '.join(DEFAULT_PREFIXES)}.", field="code_prefixes")
        prefix = str(prefix or "").strip() or DEFAULT_PREFIXES[kind]
        if not PREFIX.match(prefix):
            raise ValidationError(
                f"The prefix {prefix!r} must have one to six letters or digits, starting with a letter.",
                field="code_prefixes",
            )
        cleaned[kind] = prefix
    if len({prefix.upper() for prefix in cleaned.values()}) < len(cleaned):
        raise ValidationError("Each kind needs a prefix of its own.", field="code_prefixes")
    return cleaned


def _number(position, total):
    return str(position).zfill(len(str(total)))


def _numbered(items, prefix):
    return {item.pk: f"{prefix}{_number(index, len(items))}" for index, item in enumerate(items, start=1)}


def _tree(items, prefix):
    """Codes of research questions: the main ones numbered in their order, each sub-question under its own (RQ1.2)."""
    children = defaultdict(list)
    for item in items:
        children[item.parent_question_id].append(item)
    codes = {}

    def walk(parent_id, base):
        siblings = children.get(parent_id, [])
        for index, item in enumerate(siblings, start=1):
            number = _number(index, len(siblings))
            codes[item.pk] = f"{base}{number}" if parent_id is None else f"{base}.{number}"
            walk(item.pk, codes[item.pk])

    walk(None, prefix)
    return codes


def _coded(items, codes):
    for item in items:
        item.code = codes.get(item.pk, "")
    return items


def questions(review):
    """The review's research questions in their order, each with its ``code``."""
    items = list(review.research_questions.order_by("order", "pk"))
    return _coded(items, _tree(items, prefixes(review)[QUESTION]))


def criteria(review, criteria_type=None):
    """The review's selection criteria in their order (inclusion first), each with its ``code``."""
    own = prefixes(review)
    items = list(review.selectioncriteria_set.order_by("order", "pk"))
    inclusion = [item for item in items if item.criteria_type == SelectionCriteria.INCLUSION]
    exclusion = [item for item in items if item.criteria_type == SelectionCriteria.EXCLUSION]
    codes = {**_numbered(inclusion, own[INCLUSION]), **_numbered(exclusion, own[EXCLUSION])}
    chosen = {SelectionCriteria.INCLUSION: inclusion, SelectionCriteria.EXCLUSION: exclusion}.get(criteria_type)
    return _coded(inclusion + exclusion if chosen is None else chosen, codes)


def quality_questions(review):
    items = list(review.qualityquestion_set.order_by("order", "pk"))
    return _coded(items, _numbered(items, prefixes(review)[QUALITY]))


def fields(review):
    items = list(review.dataextractionfield_set.order_by("order", "pk"))
    return _coded(items, _numbered(items, prefixes(review)[EXTRACTION]))


def code_of(review, obj):
    """The code of one research question, criterion, quality question or extraction field of the review."""
    lists = {
        "Question": questions,
        "SelectionCriteria": criteria,
        "QualityQuestion": quality_questions,
        "DataExtractionField": fields,
    }
    found = {item.pk: item.code for item in lists[type(obj).__name__](review)}
    obj.code = found.get(obj.pk, "")
    return obj


def codes_by_id(review):
    """{"question" | "criteria" | "quality" | "extraction": {id: code}}, to label what refers to them."""
    return {
        QUESTION: {item.pk: item.code for item in questions(review)},
        "criteria": {item.pk: item.code for item in criteria(review)},
        QUALITY: {item.pk: item.code for item in quality_questions(review)},
        EXTRACTION: {item.pk: item.code for item in fields(review)},
    }


def label(code, text):
    """A name with its code: "EC2 Not in English"."""
    return f"{code} {text}" if code else (text or "")


# Codes written by hand -----------------------------------------------------------------------------------------------

# (kind, the list, its model, the field with the name)
NAMED = (
    (QUESTION, questions, Question, "question"),
    ("criteria", criteria, SelectionCriteria, "description"),
    (QUALITY, quality_questions, QualityQuestion, "description"),
    (EXTRACTION, fields, DataExtractionField, "description"),
)


def written(review):
    """
    The names that start with a code typed by hand ("RQ1: …", "QL1 | …", "EX01 | …"): for each, its ``key``
    ("question-12"), ``kind``, ``code`` (the one the review gives it now), and the name ``before`` and ``after``
    removing the code. Names that would be left empty are not listed.
    """
    rows = []
    for kind, items, _model, field in NAMED:
        for item in items(review):
            before = getattr(item, field) or ""
            match = WRITTEN.match(before)
            after = before.removeprefix(match.group(0)).strip() if match else ""
            if after:
                rows.append(
                    {
                        "key": f"{kind}-{item.pk}",
                        "kind": kind,
                        "id": item.pk,
                        "code": item.code,
                        "written": f"{match.group(1)}{match.group(2)}",
                        "before": before,
                        "after": after,
                    }
                )
    return rows


@transaction.atomic
def strip_written(*, review, keys=None, actor=None):
    """
    Remove the codes typed at the start of the names that ``written`` lists (only those of ``keys`` when given); one
    History event lists every name changed. Returns the rows changed.
    """
    rows = written(review)
    if keys is not None:
        wanted = set(keys)
        unknown = wanted - {row["key"] for row in rows}
        if unknown:
            raise ValidationError(f"No code written by hand in {sorted(unknown)}.", field="keys")
        rows = [row for row in rows if row["key"] in wanted]
    models = {kind: (model, field) for kind, _items, model, field in NAMED}
    for row in rows:
        model, field = models[row["kind"]]
        model.objects.filter(pk=row["id"]).update(**{field: row["after"]})
    if rows:
        history.record(
            review,
            ReviewEvent.REVIEW,
            history.CHANGED,
            f"Removed the codes written in {history.plural(len(rows), 'name')} (the review numbers them now)",
            subject="codes",
            items=[f"{row['before']} → {row['after']}" for row in rows],
            actor=actor,
        )
    return rows
