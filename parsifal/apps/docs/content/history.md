# History of a review

**History**, the last item of the review's menu, lists every change made to the
review: who made it, when, through what and what changed, field by field. Every
member of the review sees it. Nobody can edit or delete what it records. The
History starts with the first change made after this version was installed;
what happened before is not in it.

## What a change shows

| Column | What it says |
|--------|--------------|
| When | The time of the change, under the day's heading (hover it for the seconds) |
| Who | The person or AI agent who made it; *Parsifal* when nobody did (a management command). An agent deleted since keeps its name. |
| Area | Review, Planning, Search, Studies, Study selection, Quality assessment, Data extraction, Data analysis or Reporting |
| What | What was done: *Changed the protocol (Objective)*, *Added the AI agent “Jev”* |
| Via | Web (the browser), API, CLI, MCP (an agent through the MCP server), or Parsifal |

*details* opens what changed: each field with its value before and after, the
names of what the change took with it, the studies it applied to (each one
links to that study's own history) and the AI screening run that made it.
Each study's window (*History*, next to *External Link*) opens the changes to
that study.

## Amendments

A change to the Planning made after the first study was imported is tagged
**amendment**: the plan changed along the way. Your paper should say what
changed and why (PRISMA 2020, item 24c); *Amendments only* lists them.

## Filters

Area, action (added, changed, removed), who, through what, a period (both days
included) and words found in what was done, who did it or what changed. They
can be combined. A study's history (the link of a study in *details*) keeps
only the changes to that study.

## What is recorded

| Area | Changes |
|------|---------|
| Review | Creating the review (also from a backup); its title, description, URL and type; co-authors removed or leaving; AI agents added, given a new token or deleted; backups made, added, restored or deleted |
| Planning | The objective, the PICOC and the other protocol fields; research questions, keywords and their synonyms, the search string, sources (removing one lists the studies that went with it), inclusion and exclusion criteria and how they combine; the quality assessment questions, answers and cutoff score; the data extraction fields, their type and options. Reordering a list is a change too. |
| Search | The search string of each source; its search documentation (date of search, years, number of results); the known studies of the test set |
| Studies | Imports (the studies imported, from which source); studies added, edited, deleted (one by one, in bulk or a source cleared; their titles stay in the History); PDFs added, replaced or removed; stars |
| Study selection | The status of a study (one or many at once, with how many had each status before) and its criterion; duplicates marked; each reviewer's decisions and their consolidation; the AI screening runs — started (with the criteria sent), finished (with what they decided and the studies they changed), discarded or undone, one change per run and not per study; resetting the study selection |
| Quality assessment | Each answer given or cleared, per study and question |
| Data extraction | Each value extracted and its evidence, per study and field (before and after); a study's extraction marked done or not |
| Data analysis | The criterion of the reports not retrieved in the PRISMA flow diagram |
| Reporting | The threats to validity added, changed or removed; the manuscripts added, changed or deleted and their versions uploaded or deleted (never an amendment: they are not the protocol) |
| Review (process) | The actions of the process checklist marked as applied, and their notes |

## In the API, the CLI and the MCP server

| Interface | Usage |
|-----------|-------|
| API | `GET /api/v1/reviews/{id}/history?area=planning&since=2026-11-01&amendments=true` |
| CLI | `parsifal history list --review alice/my-review --area planning --since 2026-11-01 --amendments` |
| MCP | `parsifal_history_list` |

Each event returns `actor` (username), `actor_name`, `via`, `area`, `action`,
`summary`, `changes` (`key`, `field`, `before`, `after`), `items`,
`article_ids`, `run_id` and `amendment`.

The History goes with the review's backups: a review imported from a backup
keeps it. Restoring a backup keeps the review's History as it is and adds the
restore to it.
