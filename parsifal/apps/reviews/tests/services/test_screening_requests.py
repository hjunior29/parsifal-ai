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

STUDY_READ = {"title": "A tool", "abstract": "We built a tool."}  # the default sends no keywords

# The request as Parsifal used to word it: the review inside the question, the keywords in the state.
EDITED = {
    "state": {"title": "{{study.title}}", "keywords": "{{study.keywords}}", "abstract": "{{study.abstract}}"},
    "question": {
        "type": "choice",
        "instructions": {
            "review": "{{review}}",
            "task": "From the title, keywords and abstract: which exclusion criterion does the study meet?",
            "guidance": "{{guidance}}",
        },
        "criteria": {"none": "Nothing applies.", "{{key}}": "{{key}} — {{criterion}}"},
    },
}


def build(phase, template, guidance="", study=STUDY):
    options = {
        "exclusion": EXCLUSION_OPTIONS,
        "inclusion": INCLUSION_OPTIONS,
        "screen": EXCLUSION_OPTIONS + INCLUSION_OPTIONS,
    }[phase]
    return screening_requests.build(phase, template, options, screening_requests.values(CONTEXT, guidance, study))


def edited(phase, change):
    """The default template of ``phase`` after ``change(template)``."""
    template = screening_requests.default(phase)
    change(template)
    return template


class TestDefaultRequests(SimpleTestCase):
    def test_exclusion_one_choice_question(self):
        default = screening_requests.default("exclusion")
        state, questions = build("exclusion", default)
        self.assertEqual({"review": REVIEW, "study": STUDY_READ}, state)
        instructions = default["question"]["instructions"]
        self.assertEqual(
            {
                "exclusion": {
                    "type": "choice",
                    "instructions": {"task": instructions["task"], "rules": instructions["rules"]},
                    "criteria": {
                        "E1": "Not a primary study",
                        "E2": "Not in English",
                        "none": screening_requests.DEFAULTS["exclusion"]["question"]["criteria"]["none"],
                    },
                }
            },
            questions,
        )
        _state, with_guidance = build("exclusion", default, guidance="Tertiary studies count as secondary.")
        self.assertEqual(
            {
                "task": instructions["task"],
                "rules": instructions["rules"],
                "guidance": "Tertiary studies count as secondary.",
            },
            with_guidance["exclusion"]["instructions"],
        )

    def test_inclusion_one_yes_no_question_per_criterion(self):
        default = screening_requests.default("inclusion")
        state, questions = build("inclusion", default)
        self.assertEqual({"review": REVIEW, "study": STUDY_READ}, state)
        self.assertEqual(["inclusion_I1", "inclusion_I2"], list(questions))
        instructions = default["question"]["instructions"]
        self.assertEqual(
            {
                "type": "noul",
                "instructions": {
                    "task": instructions["task"],
                    "rules": instructions["rules"],
                    "criterion": "Implemented tool",
                },
                "criteria": {
                    "true": "Implemented tool",
                    "false": screening_requests.DEFAULTS["inclusion"]["question"]["criteria"]["false"],
                },
            },
            questions["inclusion_I2"],
        )
        self.assertEqual("inclusion_I3", screening_requests.inclusion_question_id("I3"))

    def test_screen_both_questions_in_one_request(self):
        default = screening_requests.default("screen")
        self.assertEqual({"state", "exclusion", "inclusion"}, set(default))
        self.assertEqual(screening_requests.default("exclusion")["question"], default["exclusion"])
        self.assertEqual(screening_requests.default("inclusion")["question"], default["inclusion"])
        state, questions = build("screen", default)
        self.assertEqual({"review": REVIEW, "study": STUDY_READ}, state)
        self.assertEqual(["exclusion", "inclusion_I1", "inclusion_I2"], list(questions))
        self.assertEqual({"E1", "E2", "none"}, set(questions["exclusion"]["criteria"]))
        self.assertEqual("Implemented tool", questions["inclusion_I2"]["instructions"]["criterion"])

    def test_the_defaults_keep_a_study_when_it_is_uncertain(self):
        exclusion = screening_requests.default("exclusion")["question"]["instructions"]["rules"]
        inclusion = screening_requests.default("inclusion")["question"]["instructions"]["rules"]
        self.assertIn("only if the title or abstract clearly indicates", exclusion[0])
        self.assertIn("cannot be told from the title and abstract alone", exclusion[2])
        self.assertIn("or when it cannot be told from the title and abstract alone", inclusion[0])
        self.assertIn("Answer no only if", inclusion[1])

    def test_the_default_is_a_copy(self):
        screening_requests.default("exclusion")["question"]["type"] = "changed"
        self.assertEqual("choice", screening_requests.default("exclusion")["question"]["type"])


class TestEditedRequests(SimpleTestCase):
    def test_the_text_and_layout_around_the_data_are_the_templates(self):
        state, questions = build("exclusion", EDITED, guidance="Be strict.")
        self.assertEqual(STUDY, state)
        self.assertEqual(
            {
                "exclusion": {
                    "type": "choice",
                    "instructions": {
                        "review": REVIEW,
                        "task": EDITED["question"]["instructions"]["task"],
                        "guidance": "Be strict.",
                    },
                    # The options in the template's order, the criteria where "{{key}}" is.
                    "criteria": {
                        "none": "Nothing applies.",
                        "E1": "E1 — Not a primary study",
                        "E2": "E2 — Not in English",
                    },
                }
            },
            questions,
        )
        self.assertEqual(["none", "E1", "E2"], list(questions["exclusion"]["criteria"]))

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
            questions["inclusion_I1"]["instructions"],
        )
        self.assertEqual(["false", "true"], list(questions["inclusion_I1"]["criteria"]))  # the template's order
        self.assertEqual(
            {"false": "No: Implemented tool", "true": "Yes: Implemented tool"}, questions["inclusion_I2"]["criteria"]
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
        for phase in ("exclusion", "inclusion", "screen"):
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
            ("exclusion", [], 'an object with these parts: "state", "question"'),
            ("exclusion", dict(EDITED, notes="x"), 'these parts: "state", "question"'),
            ("screen", EDITED, 'these parts: "state", "exclusion", "inclusion"'),
            (
                "screen",
                edited("screen", lambda t: t["inclusion"].update(type="choice")),
                '"inclusion" must keep "type": "noul"',
            ),
            ("screen", edited("screen", lambda t: t.update(exclusion=[])), '"exclusion" must be an object'),
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
            (
                "exclusion",
                edited("exclusion", lambda t: t["state"].update(criteria="{{exclusion_criteria}}")),
                "Unknown placeholder {{exclusion_criteria}}",
            ),
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
        self.assertFalse({"inclusion_criteria", "exclusion_criteria"} & set(names))  # Retain with AI's, removed
