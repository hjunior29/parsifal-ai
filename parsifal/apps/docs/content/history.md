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
| Area | Review, Planning, Search, Studies, Study selection, Quality assessment, Data extraction or Data analysis |
| What | What was done: *Changed the protocol (Objective)*, *Added the AI agent “Jev”* |
| Via | Web (the browser), API, CLI, MCP (an agent through the MCP server), or Parsifal |

*details* opens what changed: each field with its value before and after, the
names of what the change took with it, the studies it applied to (each one
links to that study's own history) and the AI screening run that made it.

## Amendments to the protocol

A change to the protocol (Planning) made once the first study was imported is
marked **amendment**. PRISMA 2020 asks a review to report the amendments to
its protocol (item 24c); *Amendments only* lists them.

## Filters

Area, action (added, changed, removed), who, through what, a period (both days
included) and words found in what was done, who did it or what changed. They
can be combined. A study's history (the link of a study in *details*) keeps
only the changes to that study.

## What is recorded

| Area | Changes |
|------|---------|
| Review | Creating the review (also from a backup); its title, description, URL and type; co-authors removed or leaving; AI agents added, given a new token or deleted; backups made, added, restored or deleted |
| Planning | The objective, the PICOC and the other protocol fields; research questions, keywords and their synonyms, the search string, sources (removing one lists the studies that went with it), inclusion and exclusion criteria and how they combine; the quality assessment questions, answers and cutoff score; the data extraction fields, their type and options; the classification facets and categories. Reordering a list is a change too. |
| Study selection | Resetting the study selection |

## In the API, the CLI and the MCP server

```
GET /api/v1/reviews/{id}/history?area=planning&since=2026-11-01&amendments=true
parsifal history list --review alice/my-review --area planning --since 2026-11-01 --amendments
```

Each change comes with `actor` (the username), `actor_name`, `via`, `area`,
`action`, `summary`, `changes` (`key`, `field`, `before`, `after`), `items`,
`article_ids`, `run_id` and `amendment`. The MCP server has the same as the tool
`parsifal_history_list`.

The History goes with the review's backups: a review imported from a backup
keeps it. Restoring a backup keeps the review's History as it is and adds the
restore to it.
