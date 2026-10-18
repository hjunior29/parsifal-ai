# What is new in this fork

This instance runs **parsifal-ai**, a fork of [Parsifal](https://github.com/vitorfs/parsifal)
turned into an open, self-hosted tool for conducting **systematic literature reviews**
(Kitchenham & Charters, 2007) and **systematic mapping studies** (Petersen et al., 2015)
together with AI coding agents.

Everything you knew from Parsifal still works the same way: the review page, the
Planning, Conducting and Reporting tabs, BibTeX import, study selection, quality
assessment, data extraction and the exports. These pages document only what was added.

## At a glance

| Area | What changed | Read |
|------|--------------|------|
| Deployment | Single container or process, SQLite database, one data directory, backups | [Self-hosting](/docs/self-hosting/) |
| Accounts | Closed by default: the administrator creates accounts and the main author creates AI agents as co-authors of a review; no public profiles; personal API tokens | [API tokens](/docs/api-tokens/) |
| Automation | A JSON API covering every operation of a review | [JSON API](/docs/api/) |
| Automation | The `parsifal` command-line client | [Command-line client](/docs/cli/) |
| Automation | An MCP server so Claude Code, Codex and other agents can operate reviews as tools | [MCP server](/docs/mcp/) |
| Agents | The expected division of work between an agent and the human reviewer | [Working with AI agents](/docs/agents/) |
| Methodology | Optional steps for any review — classification facets, search documentation and test set, process checklist, richer report; a mapping study is a review that uses them | [Classification and search evaluation](/docs/classification/) |
| Methodology | Independent decisions per reviewer, Cohen's kappa, consolidation rules | [Multiple reviewers and agreement](/docs/multi-reviewer/) |

## What was removed

The public-service features of parsif.al — blog, help centre, follower feed,
public profiles and pictures, e-mail invitations, ownership transfer, the
Scopus search integration, reCAPTCHA, analytics and error tracking — are gone.
Sign-up is disabled unless the administrator enables it.

## Where the source and the developer docs are

The code, issue tracker and the developer documentation (architecture, API
reference, roadmap) are in the repository's `doc/` folder:
<https://github.com/hjunior29/parsifal-ai>.
