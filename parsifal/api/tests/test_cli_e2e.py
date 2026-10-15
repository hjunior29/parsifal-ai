"""Drive a real server (LiveServerTestCase) with the real CLI through its Typer app."""

import json
import tempfile
from pathlib import Path

from django.test import LiveServerTestCase, override_settings

from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.tests.factories import DefaultSourceFactory

try:
    from typer.testing import CliRunner

    from parsifal_cli import cli
except ImportError:  # pragma: no cover
    cli = None

DATA = Path(__file__).resolve().parents[2] / "apps" / "reviews" / "tests" / "data"


@override_settings(ALLOWED_HOSTS=["*"])
class TestCliAgainstLiveServer(LiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if cli is None:
            raise cls.skipTest(cls, "parsifal-cli is not installed")

    def setUp(self):
        self.user = UserFactory(username="agent")
        _token, self.key = ApiToken.create_for(self.user, "e2e")
        self.source = DefaultSourceFactory(name="Scopus")
        self.runner = CliRunner()
        cli.state.transport = None

    def run_cli(self, *args, parse=True, **kwargs):
        result = self.runner.invoke(
            cli.app,
            ["--json", "--url", self.live_server_url, "--token", self.key, *args],
            catch_exceptions=False,
            **kwargs,
        )
        self.assertEqual(0, result.exit_code, result.output)
        if not parse or not result.output.strip():
            return None
        return json.loads(result.output)

    def test_workflow_through_cli(self):
        me = self.run_cli("me")
        self.assertEqual("agent", me["username"])

        review = self.run_cli("review", "create", "--title", "CLI driven review")
        ref = f"agent/{review['name']}"
        self.run_cli("review", "update", "--review", ref, "--population", "developers", "--intervention", "LLM")
        keywords = self.run_cli("keyword", "import-picoc", "--review", ref)
        self.assertEqual({"developers", "LLM"}, {k["description"] for k in keywords})
        generated = self.run_cli("search-string", "generate", "--review", ref)["search_string"]
        self.run_cli("search-string", "set", "--review", ref, "--search-string", "-", input=generated)
        self.run_cli("source", "add", "--review", ref, "--source-id", str(self.source.pk))
        include = self.run_cli(
            "criteria", "create", "--review", ref, "--description", "Relevant", "--criteria-type", "I"
        )

        imported = self.run_cli(
            "article",
            "import",
            "--review",
            ref,
            "--source-id",
            str(self.source.pk),
            "--bibtex",
            f"@{DATA / 'scopus_sample.bib'}",
        )
        self.assertEqual(2, imported["imported"])
        articles = self.run_cli("article", "list", "--review", ref, "--status", "U", "--all")["items"]
        ids = [str(a["id"]) for a in articles]
        self.run_cli(
            "article",
            "set-status",
            "--review",
            ref,
            "--ids",
            ids[0],
            "--ids",
            ids[1],
            "--status",
            "A",
            "--selection-criteria-id",
            str(include["id"]),
        )
        overview = self.run_cli("review", "overview", "--review", ref)
        self.assertEqual(2, overview["articles"]["accepted"])

        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.docx"
            self.run_cli("export", "report", "--review", ref, "-o", str(report), parse=False)
            self.assertEqual(b"PK", report.read_bytes()[:2])
            csv_file = Path(folder) / "articles.csv"
            self.run_cli("export", "articles", "--review", ref, "--format", "csv", "-o", str(csv_file), parse=False)
            self.assertIn("Large language models", csv_file.read_text())
