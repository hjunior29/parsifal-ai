import copy
import json

from django.test import SimpleTestCase

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.services import screening_requests

EXCLUSION_OPTIONS = [
    {"key": "E1", "id": 1, "description": "Not a primary study"},
    {"key": "E2", "id": 2, "description": "Not in English"},
]
INCLUSION_OPTIONS = [
    {"key": "I1", "id": 3, "description": "About screening"},
    {"key": "I2", "id": 4, "description": "Implemented tool"},
]
CONTEXT = {
    "title": "Screening tools",
    "objective": "Find them.",
    "research_questions": "RQ1: Which?\nRQ2: How?",
    "population": "",
    "intervention": "",
    "comparison": "",
    "outcome": "",
    "context": "",
}
STUDY = {"title": "A tool", "keywords": "screening", "abstract": "We built a tool."}
REVIEW = {"title": "Screening tools", "objective": "Find them.", "research_questions": ["RQ1: Which?", "RQ2: How?"]}

# What a reviewer tried in Jev's playground: the review in the state, no keywords, the criteria alone as options.
EDITED = {
    "state": {"review": "{{review}}", "study": {"title": "{{study.title}}", "abstract": "{{study.abstract}}"}},
    "question": {
        "type": "choice",
        "instructions": {
            "task": "From the title and abstract: which exclusion criterion do they indicate that the study meets?",
            "rules": ["Choose none only when no exclusion criterion is indicated."],
        },
        "criteria": {"{{key}}": "{{criterion}}", "none": "No exclusion criterion applies to the study."},
    },
}


def build(phase, template, guidance="", study=STUDY):
    options = INCLUSION_OPTIONS if phase == "inclusion" else EXCLUSION_OPTIONS
    return screening_requests.build(phase, template, options, screening_requests.values(CONTEXT, guidance, study))


def edited(phase, change):
    """The default template of ``phase`` after ``change(template)``."""
    template = screening_requests.default(phase)
    change(template)
    return template


class TestDefaultRequests(SimpleTestCase):
    def test_exclusion_one_choice_question_in_three_orders(self):
        default = screening_requests.default("exclusion")
        state, questions = build("exclusion", default)
        self.assertEqual(STUDY, state)
        self.assertEqual(["exclusion_1", "exclusion_2", "exclusion_3"], list(questions))
        self.assertEqual(
            [["E1", "E2", "none"], ["E2", "none", "E1"], ["none", "E1", "E2"]],
            [list(question["criteria"]) for question in questions.values()],
        )
        instructions = default["question"]["instructions"]
        self.assertEqual(
            {
                "type": "choice",
                "instructions": {"review": REVIEW, "task": instructions["task"], "rules": instructions["rules"]},
                "criteria": {
                    "E1": "Not a primary study",
                    "E2": "Not in English",
                    "none": default["question"]["criteria"]["none"],
                },
            },
            questions["exclusion_1"],
        )
        _state, with_guidance = build("exclusion", default, guidance="Tertiary studies count as secondary.")
        self.assertEqual(["review", "task", "rules", "guidance"], list(with_guidance["exclusion_2"]["instructions"]))
        self.assertEqual(
            "Tertiary studies count as secondary.", with_guidance["exclusion_2"]["instructions"]["guidance"]
        )

    def test_a_single_criterion_gives_two_orders(self):
        self.assertEqual([["E1", "none"], ["none", "E1"]], screening_requests.rotations(["E1", "none"]))
        self.assertEqual(
            ["exclusion_1", "exclusion_2"], screening_requests.exclusion_question_ids(EXCLUSION_OPTIONS[:1])
        )
        self.assertEqual(3, screening_requests.order_count("exclusion", EXCLUSION_OPTIONS))
        self.assertEqual(2, screening_requests.order_count("inclusion", INCLUSION_OPTIONS))

    def test_inclusion_one_yes_no_question_per_criterion_in_both_orders(self):
        default = screening_requests.default("inclusion")
        state, questions = build("inclusion", default, guidance="Be strict.")
        self.assertEqual(STUDY, state)
        self.assertEqual(["inclusion_i1_1", "inclusion_i1_2", "inclusion_i2_1", "inclusion_i2_2"], list(questions))
        self.assertEqual(
            [["true", "false"], ["false", "true"]],
            [list(questions[f"inclusion_i2_{order}"]["criteria"]) for order in (1, 2)],
        )
        question = questions["inclusion_i2_1"]
        self.assertEqual("noul", question["type"])
        self.assertEqual(
            {
                "true": "The study meets the inclusion criterion: Implemented tool",
                "false": "The study does not meet the inclusion criterion: Implemented tool",
            },
            question["criteria"],
        )
        instructions = default["question"]["instructions"]
        self.assertEqual(
            {
                "review": REVIEW,
                "task": instructions["task"],
                "rules": instructions["rules"],
                "guidance": "Be strict.",
                "criterion": "I2: Implemented tool",
            },
            question["instructions"],
        )

    def test_the_default_is_a_copy(self):
        screening_requests.default("exclusion")["question"]["type"] = "changed"
        self.assertEqual("choice", screening_requests.default("exclusion")["question"]["type"])


class TestEditedRequests(SimpleTestCase):
    def test_the_text_around_the_data_is_the_templates(self):
        state, questions = build("exclusion", EDITED)
        self.assertEqual({"review": REVIEW, "study": {"title": "A tool", "abstract": "We built a tool."}}, state)
        self.assertEqual(
            {
                "type": "choice",
                "instructions": EDITED["question"]["instructions"],
                "criteria": {
                    "E1": "Not a primary study",
                    "E2": "Not in English",
                    "none": "No exclusion criterion applies to the study.",
                },
            },
            questions["exclusion_1"],
        )

    def test_placeholders_inside_a_text_and_empty_values(self):
        template = {
            "state": {
                "Study": "{{study.title}} ({{study.keywords}})",
                "Population": "{{review.population}}",
                "Abstract": "{{study.abstract}}",
                "Notes": ["{{guidance}}", "Read carefully."],
            },
            "question": {
                "type": "noul",
                "instructions": "Review {{review.title}}, asking {{review.research_questions}}. Does it meet {{key}}?",
                "criteria": {"false": "No: {{criterion}}", "true": "Yes: {{criterion}}"},
            },
        }
        state, questions = build("inclusion", template)
        # Empty whole values are left out (from objects and lists alike); inside a text they are empty.
        self.assertEqual(
            {"Study": "A tool (screening)", "Abstract": "We built a tool.", "Notes": ["Read carefully."]}, state
        )
        self.assertEqual(
            {"Study": "A tool ()", "Notes": ["Read carefully."]},
            build("inclusion", template, study={"title": "A tool"})[0],
        )
        self.assertEqual(
            "Review Screening tools, asking RQ1: Which?\nRQ2: How?. Does it meet I1?",
            questions["inclusion_i1_1"]["instructions"],
        )
        # The template's order of the answers comes first.
        self.assertEqual(
            {"false": "No: About screening", "true": "Yes: About screening"}, questions["inclusion_i1_1"]["criteria"]
        )
        self.assertEqual(["true", "false"], list(questions["inclusion_i1_2"]["criteria"]))

    def test_the_options_rotate_from_the_templates_order(self):
        template = copy.deepcopy(EDITED)
        template["question"]["criteria"] = {"none": "Nothing applies.", "{{key}}": "{{key}} — {{criterion}}"}
        _state, questions = build("exclusion", template)
        self.assertEqual(
            {"none": "Nothing applies.", "E1": "E1 — Not a primary study", "E2": "E2 — Not in English"},
            questions["exclusion_1"]["criteria"],
        )
        self.assertEqual(
            [["none", "E1", "E2"], ["E1", "E2", "none"], ["E2", "none", "E1"]],
            [list(question["criteria"]) for question in questions.values()],
        )

    def test_the_state_can_be_the_study_itself(self):
        template = copy.deepcopy(EDITED)
        template["state"] = "{{study}}"
        self.assertEqual(STUDY, build("exclusion", screening_requests.clean("exclusion", template))[0])


class TestCleanTemplate(SimpleTestCase):
    def test_accepts_an_object_or_its_json_text(self):
        self.assertEqual(EDITED, screening_requests.clean("exclusion", EDITED))
        self.assertEqual(EDITED, screening_requests.clean("exclusion", json.dumps(EDITED)))
        self.assertEqual(EDITED, screening_requests.clean("exclusion", screening_requests.as_text(EDITED)))
        for phase in ("exclusion", "inclusion"):
            self.assertEqual(screening_requests.default(phase), screening_requests.clean(phase, None))
            self.assertEqual(screening_requests.default(phase), screening_requests.clean(phase, "  "))
            default = screening_requests.default(phase)
            self.assertEqual(default, screening_requests.clean(phase, default))

    def test_refuses_what_parsifal_cannot_fill_in_or_read(self):
        def question(change):
            return lambda template: change(template["question"])

        def criteria(change):
            return lambda template: change(template["question"]["criteria"])

        cases = [
            ("exclusion", '{"state": ', "not valid JSON: Expecting value (line 1, column 11)"),
            ("exclusion", [], 'an object with two parts, "state" and "question"'),
            ("exclusion", dict(EDITED, notes="x"), 'two parts, "state" and "question"'),
            ("exclusion", dict(EDITED, state="x"), '"state" must be an object'),
            ("exclusion", dict(EDITED, question=[]), '"question" must be an object'),
            ("exclusion", edited("exclusion", question(lambda q: q.update(type="noul"))), 'keep "type": "choice"'),
            ("inclusion", edited("inclusion", question(lambda q: q.pop("type"))), 'keep "type": "noul"'),
            ("exclusion", edited("exclusion", question(lambda q: q.pop("criteria"))), 'keep "criteria"'),
            ("exclusion", edited("exclusion", criteria(lambda c: c.pop("none"))), "must be two entries"),
            ("exclusion", edited("exclusion", criteria(lambda c: c.update(E9="Other"))), "must be two entries"),
            ("exclusion", edited("exclusion", criteria(lambda c: c.pop("{{key}}"))), "must be two entries"),
            ("exclusion", edited("exclusion", criteria(lambda c: c.update({"{{key}}": "{{key}}"}))), "{{criterion}}"),
            ("exclusion", edited("exclusion", criteria(lambda c: c.update(none=["x"]))), "must be texts"),
            (
                "exclusion",
                edited("exclusion", lambda t: t["state"].update(year="{{study.year}}")),
                "Unknown placeholder {{study.year}}",
            ),
            (
                "exclusion",
                edited("exclusion", lambda t: t["state"].update(title="{{study.title}")),
                "not written as {{name}}",
            ),
            (
                "exclusion",
                edited("exclusion", question(lambda q: q["instructions"].update(review="Review: {{review}}"))),
                "{{review}} is an object",
            ),
            (
                "exclusion",
                edited("exclusion", lambda t: t["state"].update(criterion="{{criterion}}")),
                '{{criterion}} cannot be used in "state"',
            ),
            (
                "exclusion",
                edited("exclusion", question(lambda q: q["instructions"].update(task="Does it meet {{key}}?"))),
                '{{key}} cannot be used in "question"',
            ),
            (
                "inclusion",
                edited("inclusion", lambda t: t["state"].update({"{{study.title}}": "x"})),
                "A field name cannot be a placeholder",
            ),
            ("exclusion", edited("exclusion", lambda t: t.update(state={"text": "No study"})), "must send the study"),
            (
                "exclusion",
                edited("exclusion", lambda t: t.update(state={"keywords": "{{study.keywords}}"})),
                "must send the study",
            ),
            ("inclusion", edited("inclusion", criteria(lambda c: c.pop("false"))), '"true" and "false"'),
            (
                "inclusion",
                edited(
                    "inclusion",
                    lambda t: t["question"].update(criteria={"true": "Yes", "false": "No"}, instructions="Is it?"),
                ),
                "asked once for every inclusion criterion",
            ),
            (
                "exclusion",
                edited("exclusion", question(lambda q: q["instructions"].update(task="x" * 20000))),
                "at most 20000 characters",
            ),
            ("exclusion", "x" * 20001, "at most 20000 characters"),
        ]
        for phase, template, message in cases:
            with self.subTest(message=message, template=str(template)[:80]):
                with self.assertRaisesMessage(ValidationError, message) as raised:
                    screening_requests.clean(phase, template)
                self.assertEqual("template", raised.exception.field)

    def test_placeholders_are_described(self):
        names = [name for name, _description in screening_requests.PLACEHOLDERS]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue({"review", "review.research_questions", "study.abstract", "key", "criterion"} <= set(names))
