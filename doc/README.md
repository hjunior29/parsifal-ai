# Parsifal-AI Documentation

Documentation for the `parsifal-ai` fork of [Parsifal](https://github.com/vitorfs/parsifal):
an open, self-hosted tool to plan, conduct and report **systematic literature
reviews** and **systematic mapping studies** in software engineering, designed
to be operated by humans through the web UI and by AI coding agents through an
API, a CLI and an MCP server.

Written 2026-10-15 against upstream version 2.2.1 (branch `dev`). All
documents are in English.

## Understanding the inherited system

| # | Document | What you will learn |
|---|----------|---------------------|
| 01 | [Project Overview](01-overview.md) | What Parsifal does, fork goals, tech stack, repository layout. |
| 02 | [Architecture](02-architecture.md) | Request flow, page vs. action routes, authorization, frontend/AJAX contract, i18n. |
| 03 | [Domain Model](03-domain-model.md) | Every model and relationship, status enums, business rules, legacy entities. |
| 04 | [Review Workflow](04-review-workflow.md) | Planning → Conducting → Reporting step by step, mapped to code and to Kitchenham's guidelines. |
| 05 | [Apps Reference](05-apps-reference.md) | One section per Django app with its disposition in the fork. |
| 06 | [HTTP Endpoint Inventory](06-http-endpoints.md) | All routes, parameters and outputs — the functional contract for the API. |
| 07 | [Import, Export and External Search](07-import-export.md) | BibTeX field mapping, XLS/DOCX exports, Scopus client. |
| 08 | [Configuration and Deployment](08-configuration-and-deployment.md) | Settings modules, environment variables, upstream deployment, CI, tooling. |
| 09 | [Testing](09-testing.md) | Current suite (75 tests, green on SQLite), conventions, gaps, policy for new code. |
| 13 | [Known Issues](13-known-issues.md) | Bugs, authorization gaps, state-changing GETs, design debt, security notes. |

## Designing the fork

| # | Document | What you will learn |
|---|----------|---------------------|
| 10 | [Methodology](10-methodology.md) | Kitchenham 2007 coverage matrix; what Petersen 2015 mapping studies require; proposed model additions. |
| 11 | [System Design](11-system-design.md) | Service layer, SQLite data dir, API tokens, JSON API resource map, CLI, MCP, packaging, coding conventions. |
| 12 | [Roadmap](12-roadmap.md) | Phases 0–10 with deliverables, tests and acceptance criteria; phases 0–4 done. |
| 14 | [JSON API v1](14-api.md) | Authentication with tokens, conventions, every resource and operationId, curl walkthrough, bootstrap commands. |
| 15 | [CLI and MCP server](15-cli-and-mcp.md) | Installing and configuring `parsifal`, the command tree, conventions and exit codes, agent example; MCP server (phase 5). |
| — | [Decisions (ADRs)](decisions.md) | SQLite · API-first · trim SaaS · single admin + tokens · Python ≥ 3.10, Django 4.2 for now · SLR+SMS · docs in English. |

Planned additions as phases land: `16-self-hosting.md`; phase 9 adds in-app
documentation pages for the new features.

## Reference material

- Kitchenham & Charters (2007) and Petersen et al. (2015) are kept as
  structured Markdown outside this repository and indexed in a local
  [code-rag](https://github.com/hjunior29/code-rag) instance together with
  this codebase (projects `parsifal`, `kitchenham-2007`, `petersen-2015`).
  See [10-methodology.md](10-methodology.md) §5 for query examples.
