"""
End-to-end scenario: an agent drives a complete systematic review through the JSON API alone — protocol,
import, screening, quality assessment, data extraction, analytics and the DOCX report.
"""

from pathlib import Path

from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.reviews.tests.factories import DefaultSourceFactory

DATA = Path(__file__).resolve().parents[2] / "apps" / "reviews" / "tests" / "data"


class TestFullReviewThroughApi(ApiTestCase):
    def ok(self, response, status=200):
        self.assertEqual(status, response.status_code, response.content[:500])
        return response.json() if response.content else None

    def test_full_workflow(self):
        scopus = DefaultSourceFactory(name="Scopus")

        # Planning -----------------------------------------------------------------------------------------------
        review = self.ok(self.api("post", "/reviews", {"title": "LLM-assisted SLRs", "description": "e2e"}), 201)
        rid = review["id"]
        p = lambda suffix="": f"/reviews/{rid}{suffix}"  # noqa: E731

        self.ok(
            self.api(
                "patch",
                p(),
                {
                    "objective": "Understand tool support",
                    "population": "researchers",
                    "intervention": "LLM tools",
                    "outcome": "effort",
                },
            )
        )
        self.ok(self.api("post", p("/questions"), {"description": "RQ1: Which tools exist?"}), 201)
        self.ok(self.api("post", p("/questions"), {"description": "RQ2: How are they evaluated?"}), 201)
        keywords = self.ok(self.api("post", p("/keywords/import-picoc")))
        llm = next(k for k in keywords if k["description"] == "LLM tools")
        self.ok(self.api("patch", p(f"/keywords/{llm['id']}"), {"synonyms": ["large language model"]}))
        generated = self.ok(self.api("post", p("/search-string/generate")))["search_string"]
        self.ok(self.api("put", p("/search-string"), {"search_string": generated}))
        self.ok(self.api("post", p("/sources"), {"source_id": scopus.pk}), 201)
        self.ok(self.api("post", p(f"/sources/{scopus.pk}/search-string/copy-generic")))
        include = self.ok(
            self.api("post", p("/criteria"), {"description": "Primary study about SLR tooling", "criteria_type": "I"}),
            201,
        )
        exclude = self.ok(
            self.api("post", p("/criteria"), {"description": "Not in English", "criteria_type": "E"}), 201
        )
        q1 = self.ok(self.api("post", p("/quality/questions"), {"description": "Is the evaluation rigorous?"}), 201)
        answers = self.ok(self.api("post", p("/quality/answers/suggested")), 201)
        yes = next(a for a in answers if a["description"] == "Yes")
        no = next(a for a in answers if a["description"] == "No")
        self.ok(self.api("put", p("/quality/cutoff"), {"cutoff": 0.5}))
        tool = self.ok(self.api("post", p("/extraction/fields"), {"description": "Tool name", "field_type": "S"}), 201)
        method = self.ok(
            self.api(
                "post",
                p("/extraction/fields"),
                {"description": "Method", "field_type": "O", "lookup_values": ["Experiment", "Case study"]},
            ),
            201,
        )

        # Conducting ---------------------------------------------------------------------------------------------
        imported = self.ok(
            self.api(
                "post",
                p("/articles/import"),
                {"source_id": scopus.pk, "bibtex": (DATA / "scopus_sample.bib").read_text()},
            ),
            201,
        )
        self.assertEqual(2, imported["imported"])
        self.ok(
            self.api(
                "post",
                p("/articles/import"),
                {"source_id": scopus.pk, "bibtex": (DATA / "ieee_sample.bib").read_text()},
            ),
            201,
        )
        duplicates = self.ok(self.api("get", p("/articles/duplicates")))
        self.assertEqual(1, len(duplicates["groups"]))
        self.ok(self.api("post", p("/articles/duplicates/resolve"), {}))

        unclassified = self.ok(self.api("get", p("/articles?status=U")))["items"]
        self.assertEqual(3, len(unclassified))
        smith = next(a for a in unclassified if a["bibtex_key"] == "Smith2020")
        jones = next(a for a in unclassified if a["bibtex_key"] == "Jones2019")
        lee = next(a for a in unclassified if a["bibtex_key"] == "8812345")
        self.ok(
            self.api(
                "post",
                p("/articles/status"),
                {"ids": [smith["id"], lee["id"]], "status": "A", "selection_criteria_id": include["id"]},
            )
        )
        self.ok(
            self.api(
                "post",
                p("/articles/status"),
                {
                    "ids": [jones["id"]],
                    "status": "R",
                    "selection_criteria_id": exclude["id"],
                    "comments": "abstract only",
                },
            )
        )

        self.ok(
            self.api("put", p(f"/articles/{smith['id']}/quality"), {"question_id": q1["id"], "answer_id": yes["id"]})
        )
        self.ok(self.api("put", p(f"/articles/{lee['id']}/quality"), {"question_id": q1["id"], "answer_id": no["id"]}))
        summary = self.ok(self.api("get", p("/quality/summary")))
        passes = {row["article_id"]: row["passes_cutoff"] for row in summary["articles"]}
        self.assertEqual({smith["id"]: True, lee["id"]: False}, passes)

        self.ok(
            self.api("put", p(f"/articles/{smith['id']}/extraction"), {"field_id": tool["id"], "value": "ReviewBot"})
        )
        experiment = next(lk for lk in method["lookup_values"] if lk["value"] == "Experiment")
        self.ok(
            self.api(
                "put", p(f"/articles/{smith['id']}/extraction"), {"field_id": method["id"], "value": experiment["id"]}
            )
        )
        self.ok(self.api("put", p(f"/articles/{smith['id']}/extraction/done"), {"done": True}))

        # Analysis and reporting ---------------------------------------------------------------------------------
        overview = self.ok(self.api("get", p("/overview")))
        self.assertEqual(
            {
                "total": 4,
                "unclassified": 0,
                "accepted": 2,
                "rejected": 1,
                "duplicated": 1,
                "final_selection": 1,
                "extraction_done": 1,
            },
            overview["articles"],
        )
        by_source = self.ok(self.api("get", p("/analytics/selection-by-source")))
        self.assertEqual([("Scopus", 4, 2)], [(r["source"], r["total"], r["accepted"]) for r in by_source])
        by_year = self.ok(self.api("get", p("/analytics/final-by-year")))
        self.assertEqual([{"year": 2020, "count": 1}], by_year)

        matrix = self.ok(self.api("get", p("/export/extraction.json")))
        self.assertEqual([{"article": smith["title"], "Tool name": "ReviewBot", "Method": "Experiment"}], matrix)
        report = self.api("get", p("/export/report.docx"))
        self.assertEqual(200, report.status_code)
        self.assertGreater(len(report.content), 1000)
