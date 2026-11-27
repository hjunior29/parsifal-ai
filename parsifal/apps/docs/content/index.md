# What is new in this fork

This instance runs **parsifal-ai**, a fork of [Parsifal](https://github.com/vitorfs/parsifal)
turned into an open, self-hosted tool for conducting **systematic literature reviews**
([Kitchenham & Charters, 2007](https://www.elsevier.com/__data/promis_misc/525444systematicreviewsguide.pdf)),
**systematic mapping studies** ([Petersen et al., 2015](https://doi.org/10.1016/j.infsof.2015.03.007))
and **rapid reviews** ([Cartaxo et al., 2020](https://arxiv.org/abs/2003.10006)) together with AI coding agents.

Everything you knew from Parsifal still works the same way: the review page, the
Planning, Conducting and Reporting tabs, BibTeX import, study selection, quality
assessment, data extraction and the exports. These pages document only what was added.

## At a glance

| Area | What changed | Read |
|------|--------------|------|
| Deployment | Single container or process, SQLite database, one data directory, backups | [Self-hosting](/docs/self-hosting/) |
| Accounts | Closed by default: the administrator creates accounts and the main author creates AI agents as co-authors of a review; no public profiles; personal API tokens | [API tokens](/docs/api-tokens/) |
| Theme | *Settings → Profile → Theme*: the system's (light or dark, as the device is set), light or dark | `me-update --theme` |
| Backups | *Review settings → Backups*: back the review up (everything of it, PDFs included) into a list kept on the server, download, restore over the review or delete; *New review → Import a review backup* creates a review from one, here or in another Parsifal | `review backup …`, `review import` |
| AI screening | *Screen with AI* (Jev): reject by exclusion criteria, accept by inclusion criteria, or both in one run, with per-criterion thresholds, per-round screening, AI relevance percentage and resumable runs | [Exclude, include and screen with AI (Jev)](/docs/ai-screening/) |
| Studies | Choose and order columns (*Columns* next to the search on Study Selection); paginated study list (25 by default, up to 100), filtered, searched and sorted as a whole; *Select all N studies* applies actions across every page; attach one PDF per study (local or S3) | `article set-status` / `delete-batch --all-matching` |
| Library access | *Via CAPES* in the study window and on *Search*: open each study at the publisher, and each source, with your institution's access (CAFe), configured in *Settings → Library access* | [Open studies through CAPES](/docs/library-access/) |
| Search | *Import Studies* stores the **Date of Search** of each source (PRISMA 2020 item 6), saved immediately and included in the report's search documentation | `source imports`, `article import --searched-at`, `source document-search --searched-at` |
| Multi-reviewer | Independent decisions per reviewer, Cohen's kappa comparing any two reviewers, disagreement listing and consolidation rules (unanimous, majority, any include) | [Multiple reviewers and agreement](/docs/multi-reviewer/) |
| Mapping studies | Optional steps for any review — search documentation and known-paper test set, Petersen process checklist; studies classified with the choice fields of the extraction form | [Classification and search evaluation](/docs/classification/) |
| Codes | The review numbers its research questions (RQ1, RQ1.1), selection criteria (IC1, EC1), quality questions (QA1) and extraction fields (EX1) from their order, with prefixes of its own (QP, CI, CE… for a review in Portuguese); the criteria have ordered lists of their own; *Review settings → Codes* removes the codes typed by hand in the names | [Codes](/docs/codes/) · `review codes …`, `criteria reorder` |
| Rapid reviews | A review type of its own ([Cartaxo et al., 2020](https://arxiv.org/abs/2003.10006)): **practical context** in the protocol, **Rapid Review Checklist** of practitioner collaboration and concessions (from which threats to validity are drafted), and **screening rounds** (titles → titles and abstracts → full text) with PRISMA split by round | [Rapid reviews](/docs/rapid-review/) · `review update --demand …`, `checklist get --catalog rapid`, `threat draft`, `article set-status --stage` |
| Extraction | Each value of *Data Extraction* carries its **evidence** (passage, page, figure or table) written under the value; a study is marked done only when every value has evidence, and all exports carry it | `extraction set --evidence`, `extraction evidence` |
| Quality & extraction UI | Collapsible panels per study, search by title, pagination, *Study* view with full-text PDF, and click-again to clear a quality answer | — |
| Analysis | *Data Analysis* has three sections: study selection (the **PRISMA 2020 flow diagram** downloadable as SVG or PNG, selection funnel, criteria most used), quality assessment (scores, answers per question) and data extraction (charts per choice/boolean field) | — |
| History | **History** in the review's menu: every change to the review — who made it, when, through what (web, API, CLI, MCP) and what changed — with filters; protocol changes after studies are imported are marked as **amendments** (PRISMA 2020 item 24c) | [History of a review](/docs/history/) · `history list` |
| Progress | A **progress bar** under the review's title on every page of the review and in the list of reviews (Planning 20%, Conducting 70%, Reporting 10%), complete once all remaining studies are extracted and a manuscript has a version | `review progress` |
| Reporting | **Threats to Validity** (free type with Petersen 2015 / Wohlin 2012 suggestions, description and mitigation) and **Manuscripts** (any name, versioned uploads, in-page PDF viewer), plus DOCX, XLSX, CSV and JSON exports | [Reporting](/docs/reporting/) · `threat …`, `manuscript …` |
| Automation | A JSON API covering every operation of a review, with interactive OpenAPI docs at `/api/v1/docs` | [JSON API](/docs/api/) |
| Automation | The `parsifal` command-line client with JSON output for scripts | [Command-line client](/docs/cli/) |
| Automation | The `parsifal-mcp` server (stdio or HTTP) so Claude Code, Codex and other agents operate reviews as tools | [MCP server](/docs/mcp/) |
| Agents | Expected division of work between an AI agent and the human reviewer | [Working with AI agents](/docs/agents/) |

## What was removed

The public-service features of parsif.al — blog, help centre, follower feed,
public profiles and pictures, e-mail invitations, ownership transfer, the
Scopus search integration, reCAPTCHA, analytics and error tracking — are gone.
Sign-up is disabled unless the administrator enables it.

## Where the source and the developer docs are

The code, issue tracker and the developer documentation (architecture, API
reference, roadmap) are in the repository's `doc/` folder:
<https://github.com/hjunior29/parsifal-ai>.
