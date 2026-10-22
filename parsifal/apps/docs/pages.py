"""
In-app documentation: Markdown files under ``content/`` rendered inside the site's layout.

Only the features this fork adds are documented here (self-hosting, tokens, API, CLI, MCP, agents, mapping
studies, multi-reviewer screening, AI exclusion screening, library access); the inherited review workflow is
self-explanatory in the UI.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings

import markdown

CONTENT_DIR = Path(__file__).resolve().parent / "content"

MARKDOWN_EXTENSIONS = ["fenced_code", "tables", "sane_lists", "toc"]


@dataclass(frozen=True)
class Page:
    slug: str
    title: str
    section: str
    summary: str

    @property
    def path(self):
        return CONTENT_DIR / f"{self.slug}.md"


PAGES = (
    Page("index", "What is new in this fork", "Getting started", "Self-hosted Parsifal for humans and AI agents."),
    Page("self-hosting", "Self-hosting", "Getting started", "Run your own instance with Docker or Python."),
    Page(
        "library-access",
        "Open studies through CAPES",
        "Getting started",
        "Via CAPES: each study at the publisher with your institution's access, signed in through CAFe.",
    ),
    Page("api-tokens", "API tokens", "Automation", "Give scripts and agents access with your permissions."),
    Page("api", "JSON API", "Automation", "Every review operation over HTTP."),
    Page("cli", "Command-line client", "Automation", "The parsifal command."),
    Page("mcp", "MCP server", "Automation", "Connect Claude Code, Codex and other agents."),
    Page("agents", "Working with AI agents", "Automation", "How an agent is expected to drive a review."),
    Page(
        "classification",
        "Classification and search evaluation",
        "Methodology",
        "Optional steps: facets, test set, checklist — what a mapping study uses.",
    ),
    Page(
        "multi-reviewer",
        "Multiple reviewers and agreement",
        "Methodology",
        "Independent decisions, kappa, consolidation.",
    ),
    Page(
        "ai-screening",
        "Exclude, include and screen with AI (Jev)",
        "Methodology",
        "Study selection by Jev: reject by exclusion criteria, accept by inclusion criteria, or both in one request.",
    ),
)

BY_SLUG = {page.slug: page for page in PAGES}


def sections():
    """Pages grouped by section, in declaration order."""
    grouped = {}
    for page in PAGES:
        grouped.setdefault(page.section, []).append(page)
    return grouped


def render_markdown(text):
    return markdown.markdown(text, extensions=MARKDOWN_EXTENSIONS, output_format="html5")


@lru_cache(maxsize=None)
def _render_cached(slug):
    return render_markdown(BY_SLUG[slug].path.read_text(encoding="utf-8"))


def render_page(page):
    if settings.DEBUG:  # pick up edits without restarting the dev server
        return render_markdown(page.path.read_text(encoding="utf-8"))
    return _render_cached(page.slug)
