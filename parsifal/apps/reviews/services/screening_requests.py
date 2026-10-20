"""
What an AI screening run (Exclude with AI, Include with AI) sends to Jev for each study, as a template the reviewer
can edit. A template is a JSON object with two parts: ``state``, what Jev reads about the study, and ``question``,
what Jev is asked about it.

Everything in a template can be edited except the data, which are placeholders that Parsifal fills in:

- the review context, from the run's context fields: ``{{review}}`` (all of it, as an object) or one field at a time,
  ``{{review.title}}``, ``{{review.objective}}``, ``{{review.research_questions}}``…;
- ``{{guidance}}``, the run's extra guidance;
- the study: ``{{study}}`` (as an object), ``{{study.title}}``, ``{{study.keywords}}``, ``{{study.abstract}}``;
- the criteria, from the protocol: ``{{key}}`` (E1, I1…) and ``{{criterion}}`` (its description).

A placeholder that is a whole value is replaced by the value itself (an object for ``{{review}}``, a list for the
research questions), and when that value is empty the entry is left out, so empty context fields are not sent.
Inside a longer text a placeholder is replaced by its text.

Parsifal still decides how the question is repeated, because that is how it combines the answers:

- Exclusion: a ``choice`` question whose ``criteria`` have one entry keyed ``{{key}}``, repeated for every exclusion
  criterion, and one keyed ``none``. It is asked in up to three orders of those options (rotations of the template's
  order), because the model tends to favour the first option when unsure.
- Inclusion: a ``noul`` (yes/no) question, asked for every inclusion criterion, whose ``criteria`` describe the
  ``true`` and ``false`` answers. It is asked in the template's order of the two and in the reverse one.
"""

import copy
import json
import re

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import ScreeningRun

EXCLUSION, INCLUSION = ScreeningRun.EXCLUSION, ScreeningRun.INCLUSION
CHOICE, NOUL = "choice", "noul"  # Jev's question types: one of several options; yes/no (answer: p(yes))
QUESTION_TYPES = {EXCLUSION: CHOICE, INCLUSION: NOUL}
NONE = "none"  # the exclusion option that no criterion applies
YES, NO = "true", "false"  # the answers of a yes/no question
ORDERS = 3  # option orders of the exclusion question asked per study
MAX_LENGTH = 20000  # characters of a template, as JSON

REVIEW_FIELDS = (
    "title",
    "objective",
    "research_questions",
    "population",
    "intervention",
    "comparison",
    "outcome",
    "context",
)
STUDY_FIELDS = ("title", "keywords", "abstract")
PLACEHOLDERS = (
    ("review", "The review context: an object with its fields that are not empty (research questions as a list)."),
    ("review.title", "Review title."),
    ("review.objective", "Objective."),
    ("review.research_questions", "Research questions: a list, one per line of the field (one per line in a text)."),
    ("review.population", "Population."),
    ("review.intervention", "Intervention."),
    ("review.comparison", "Comparison."),
    ("review.outcome", "Outcome."),
    ("review.context", "Context."),
    ("guidance", "Extra guidance."),
    ("study", "The study: an object with its title, keywords and abstract that are not empty."),
    ("study.title", "The study's title."),
    ("study.keywords", "The study's author keywords, or its keywords when it has none."),
    ("study.abstract", "The study's abstract."),
    ("key", "The criterion's key: E1, E2… (exclusion) or I1, I2… (inclusion)."),
    ("criterion", "The criterion's description, from the protocol."),
)
NAMES = {name for name, _description in PLACEHOLDERS}
CRITERION_NAMES = {"key", "criterion"}  # only where a criterion is asked about
DATA_NAMES = NAMES - CRITERION_NAMES
OBJECT_NAMES = {"review", "study"}  # whole values only
STUDY_NAMES = {"study", "study.title", "study.abstract"}  # Jev must read one of them
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_.]+)\s*\}\}")

_STATE = {"title": "{{study.title}}", "keywords": "{{study.keywords}}", "abstract": "{{study.abstract}}"}
DEFAULTS = {
    EXCLUSION: {
        "state": _STATE,
        "question": {
            "type": CHOICE,
            "instructions": {
                "review": "{{review}}",
                "task": "Screening for a systematic review, phase 1 (exclusion only), from the title, keywords and "
                "abstract of a study: which exclusion criterion does the study meet?",
                "rules": [
                    "Choose a criterion only if the title, keywords or abstract explicitly support it.",
                    "If several criteria apply, choose the one most clearly supported.",
                    "If no criterion applies, or the title, keywords and abstract do not give enough information to "
                    "decide, choose none.",
                ],
                "guidance": "{{guidance}}",
            },
            "criteria": {
                "{{key}}": "{{criterion}}",
                NONE: "No exclusion criterion is clearly supported by the title, keywords or abstract, or they do "
                "not give enough information to decide.",
            },
        },
    },
    INCLUSION: {
        "state": _STATE,
        "question": {
            "type": NOUL,
            "instructions": {
                "review": "{{review}}",
                "task": "Screening for a systematic review, phase 2 (inclusion), from the title, keywords and "
                "abstract of a study: does the study meet this inclusion criterion?",
                "rules": [
                    "Answer yes only if the title, keywords or abstract explicitly support that the study meets the "
                    "criterion.",
                    "Answer no only if the title, keywords or abstract explicitly show that the study does not meet "
                    "it.",
                    "Missing information is not a no: if the title, keywords and abstract do not give enough "
                    "information to decide, the answer is uncertain.",
                ],
                "guidance": "{{guidance}}",
                "criterion": "{{key}}: {{criterion}}",
            },
            "criteria": {
                YES: "The study meets the inclusion criterion: {{criterion}}",
                NO: "The study does not meet the inclusion criterion: {{criterion}}",
            },
        },
    },
}


def default(phase):
    """Parsifal's template for ``phase``."""
    return copy.deepcopy(DEFAULTS[phase])


def as_text(template):
    """The template as the web shows it for editing."""
    return json.dumps(template, indent=2, ensure_ascii=False)


# Checking a template -------------------------------------------------------------------------------------------------


def _placeholder(name):
    return "{{" + name + "}}"


def _whole(text):
    """The name of the placeholder that makes up all of ``text``, or None."""
    match = PLACEHOLDER.fullmatch(text.strip())
    return match.group(1) if match else None


def _invalid(message):
    return ValidationError(message, field="template")


def _names(text, where, allowed):
    """The placeholders of a text, checked: known, allowed in that part, objects only as a whole value."""
    leftover = PLACEHOLDER.sub("", text)
    if "{{" in leftover or "}}" in leftover:
        raise _invalid(f"A placeholder in {where} is not written as {{{{name}}}}: {text[:80]!r}.")
    whole = _whole(text)
    names = set()
    for match in PLACEHOLDER.finditer(text):
        name = match.group(1)
        if name not in NAMES:
            raise _invalid(f"Unknown placeholder {_placeholder(name)} in {where}.")
        if name not in allowed:
            raise _invalid(f"{_placeholder(name)} cannot be used in {where}.")
        if name in OBJECT_NAMES and whole != name:
            raise _invalid(
                f"{_placeholder(name)} is an object: use it as a whole value in {where}, or its fields "
                f"({_placeholder(name + '.title')}…) inside a text."
            )
        names.add(name)
    return names


def _walk(node, where, allowed):
    """The placeholders used anywhere in ``node``; field names cannot be placeholders."""
    if isinstance(node, str):
        return _names(node, where, allowed)
    names = set()
    if isinstance(node, list):
        for item in node:
            names |= _walk(item, where, allowed)
    elif isinstance(node, dict):
        for key, value in node.items():
            if "{{" in key or "}}" in key:
                raise _invalid(
                    f"A field name cannot be a placeholder ({key!r} in {where}); only the exclusion options have "
                    f"one entry keyed {{{{key}}}}."
                )
            names |= _walk(value, where, allowed)
    return names


def clean(phase, template):
    """
    ``template`` (an object, or its JSON text) checked for ``phase``; None or a blank text is Parsifal's default.
    Raises ValidationError (field "template") saying what is wrong.
    """
    if template is None or (isinstance(template, str) and not template.strip()):
        return default(phase)
    too_long = _invalid(f"The request template must have at most {MAX_LENGTH} characters.")
    if isinstance(template, str):
        if len(template) > MAX_LENGTH:
            raise too_long
        try:
            template = json.loads(template)
        except json.JSONDecodeError as error:
            raise _invalid(
                f"The request template is not valid JSON: {error.msg} (line {error.lineno}, column {error.colno})."
            )
    if not isinstance(template, dict) or set(template) != {"state", "question"}:
        raise _invalid('The request template must be an object with two parts, "state" and "question".')
    if len(json.dumps(template, ensure_ascii=False)) > MAX_LENGTH:
        raise too_long

    state, question = template["state"], template["question"]
    if not isinstance(state, dict) and not (isinstance(state, str) and _whole(state) == "study"):
        raise _invalid('"state" must be an object: what Jev reads about each study.')
    used = _walk(state, '"state"', DATA_NAMES)
    if not isinstance(question, dict):
        raise _invalid('"question" must be an object: what Jev is asked about each study.')
    expected = QUESTION_TYPES[phase]
    if question.get("type") != expected:
        raise _invalid(f'The question must keep "type": "{expected}", the kind of answer Parsifal reads.')
    criteria = question.get("criteria")
    if not isinstance(criteria, dict):
        raise _invalid('The question must keep "criteria", the answers Jev chooses from.')
    rest = {key: value for key, value in question.items() if key != "criteria"}

    if phase == EXCLUSION:
        used |= _walk(rest, '"question"', DATA_NAMES)
        repeated = [key for key in criteria if _whole(key) == "key"]
        if len(repeated) != 1 or NONE not in criteria or len(criteria) != 2:
            raise _invalid(
                'The exclusion options ("criteria") must be two entries: "{{key}}", repeated for every exclusion '
                'criterion, and "none".'
            )
        option, none = criteria[repeated[0]], criteria[NONE]
        if not isinstance(option, str) or not isinstance(none, str):
            raise _invalid('The "{{key}}" and "none" options must be texts.')
        option_names = _names(option, 'the "{{key}}" option', NAMES)
        if "criterion" not in option_names:
            raise _invalid('The "{{key}}" option must include {{criterion}}, the criterion it stands for.')
        used |= option_names | _names(none, 'the "none" option', DATA_NAMES)
    else:
        asked = _walk(rest, '"question"', NAMES)
        if set(criteria) != {YES, NO} or not all(isinstance(text, str) for text in criteria.values()):
            raise _invalid('The answers ("criteria") of the yes/no question must be "true" and "false", each a text.')
        for answer, text in criteria.items():
            asked |= _names(text, f'the "{answer}" answer', NAMES)
        if "criterion" not in asked:
            raise _invalid("The question must include {{criterion}}: it is asked once for every inclusion criterion.")
        used |= asked
    if not used & STUDY_NAMES:
        raise _invalid("The request must send the study: use {{study.title}} or {{study.abstract}} (or {{study}}).")
    return template


# Building a request --------------------------------------------------------------------------------------------------


_OMIT = object()  # a whole placeholder with nothing to fill in: its entry is left out


def _empty(value):
    return value is None or value == "" or value == [] or value == {}


def _text(value):
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return "" if value is None else str(value)


def _fill(node, values):
    if isinstance(node, str):
        name = _whole(node)
        if name is not None:
            value = values.get(name)
            return _OMIT if _empty(value) else copy.deepcopy(value)
        return PLACEHOLDER.sub(lambda match: _text(values.get(match.group(1))), node)
    if isinstance(node, list):
        return [item for item in (_fill(item, values) for item in node) if item is not _OMIT]
    if isinstance(node, dict):
        filled = {key: _fill(value, values) for key, value in node.items()}
        return {key: value for key, value in filled.items() if value is not _OMIT}
    return node


def _fill_text(text, values):
    filled = _fill(text, values)
    return "" if filled is _OMIT else filled


def values(context, guidance, study=None):
    """
    What the placeholders stand for: the run's context fields and guidance, and the study (title, keywords, abstract
    that are not empty, as ``ai_screening.state`` gives them).
    """
    review = {}
    for name in REVIEW_FIELDS:
        value = context.get(name)
        if value and name == "research_questions":
            review[name] = [line.strip() for line in value.splitlines() if line.strip()]
        elif value:
            review[name] = value
    study = study or {}
    filled = {"review": review, "guidance": guidance or "", "study": study}
    filled.update({f"review.{name}": review.get(name, "") for name in REVIEW_FIELDS})
    filled.update({f"study.{name}": study.get(name, "") for name in STUDY_FIELDS})
    return filled


def rotations(keys):
    """Up to ORDERS distinct rotations of ``keys``, so that every option changes position."""
    orders = []
    for index in range(ORDERS):
        shift = index * len(keys) // ORDERS
        order = keys[shift:] + keys[:shift]
        if order not in orders:
            orders.append(order)
    return orders


def exclusion_question_ids(options):
    """One id per order of the exclusion question: exclusion_1, exclusion_2…"""
    return [f"exclusion_{index}" for index in range(1, len(rotations(list(range(len(options) + 1)))) + 1)]


def inclusion_question_ids(options):
    """{criterion key: the ids of its question in each order}, e.g. {"I1": ["inclusion_i1_1", "inclusion_i1_2"]}."""
    return {option["key"]: [f"inclusion_{option['key'].lower()}_{order}" for order in (1, 2)] for option in options}


def order_count(phase, options):
    return 2 if phase == INCLUSION else len(exclusion_question_ids(options))


def _with_criteria(question, values, criteria):
    """``question`` filled in, with ``criteria`` in the place of its own."""
    return {key: criteria if key == "criteria" else value for key, value in _fill(question, values).items()}


def _about(values, option):
    return dict(values, key=option["key"], criterion=option["description"])


def _exclusion_questions(question, options, values):
    texts = {}  # option key (E1…, none) -> its text, in the template's order
    for key, text in question["criteria"].items():
        if key == NONE:
            texts[NONE] = _fill_text(text, values)
        else:
            for option in options:
                texts[option["key"]] = _fill_text(text, _about(values, option))
    return {
        question_id: _with_criteria(question, values, {key: texts[key] for key in order})
        for question_id, order in zip(exclusion_question_ids(options), rotations(list(texts)))
    }


def _inclusion_questions(question, options, values):
    answers = list(question["criteria"])  # true and false, in the template's order
    ids = inclusion_question_ids(options)
    asked = {}
    for option in options:
        about = _about(values, option)
        texts = {answer: _fill_text(question["criteria"][answer], about) for answer in answers}
        for question_id, order in zip(ids[option["key"]], (answers, answers[::-1])):
            asked[question_id] = _with_criteria(question, about, {answer: texts[answer] for answer in order})
    return asked


def build(phase, template, options, values):
    """The ``state`` and ``questions`` sent to Jev for one study (``values`` with the study)."""
    state = _fill(template["state"], values)
    build_questions = _inclusion_questions if phase == INCLUSION else _exclusion_questions
    return ({} if state is _OMIT else state), build_questions(template["question"], options, values)
