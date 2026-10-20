# Working with AI agents

Parsifal does not run language models itself. It gives agents (Claude Code,
Codex, custom scripts) the same operations a human has, through the
[API](/docs/api/), the [CLI](/docs/cli/) and the [MCP server](/docs/mcp/), and it
records **who** did what, so the human author stays accountable for the review.

## Set-up that keeps you in control

1. Create the agent **from the review**: *Review settings → Manage access →
   Create an AI agent as co-author* (or `parsifal agent create`, `POST
   /api/v1/reviews/{id}/agents`). It gets an account of its own for that review,
   with co-author permissions, and its API token is shown **once**. Everything
   it writes is attributed to it, and its screening decisions count as one more
   reviewer. There is no way to add an existing account.
2. Keep the main authorship: only the main author can delete or rename the
   review or manage its agents (an agent cannot create or delete agents).
   `agent new-token` replaces a token you lost; `agent delete` ends the agent.
   Deleting an agent is permanent: it deletes the account, its API tokens and everything recorded under it (screening decisions, quality assessments, extracted data). Studies it imported and classifications it made stay in the review, without an author.
3. Prefer **independent decisions** over direct status changes during
   screening (next section), so the agent's judgement can be measured before
   it affects the selection.

## What an agent can do at each phase

| Phase | Typical agent tasks | Tools / commands |
|-------|---------------------|------------------|
| Planning | Draft objective and PICOC from your research idea; propose research questions, keywords and synonyms; generate and refine the search string; suggest inclusion/exclusion criteria, a quality checklist and extraction fields | `reviews_update`, `questions_create`, `keywords_create`, `search_string_generate`, `criteria_create`, `quality_questions_create`, `extraction_fields_create` |
| Search | Document each source search (type, date, years, results); import BibTeX exports; detect duplicates | `source_search_update`, `articles_import`, `articles_duplicates`, `articles_resolve_duplicates` |
| Selection | Screen titles and abstracts against the criteria, in batches, recording a decision and the criterion as reason | `articles_screen_batch`, `decisions_record` (recommended) or `articles_set_status` |
| Quality assessment | Read the study's PDF when it has one; answer the checklist per accepted study, with notes | `articles_pdf_download`, `article_quality_assess` |
| Extraction / classification | Fill extraction fields; classify studies into facets | `article_extraction_set`, `article_classification_set` |
| Reporting | Read analytics and exports, draft the report text around them | `analytics_*`, `export_*`, `reviews_overview` |

## Screening with independent decisions

1. The agent records its decisions with `decisions_record` (stage
   `title_abstract` first, `full_text` later), always with a criterion id as
   the reason and a short comment.
2. You record yours — in the UI (study selection sets the consolidated status)
   or also as decisions (`parsifal decision record …`).
3. Compare: `decisions_agreement` gives percent agreement and Cohen's kappa;
   `decisions_disagreements` lists the studies to discuss.
4. Consolidate: `decisions_consolidate` with the rule you decided in the
   protocol — `unanimous`, `any_include` (a study passes to the next stage if
   any reviewer includes it) or `majority` — and resolve the rest by hand.

Record the rule and the kappa in the protocol (`selection_procedure`) and in
the report; both guidelines ask for it.

## Guard-rails

- Agents only act within the reviews they are members of; a review they are
  not part of does not exist for them (`404`).
- Destructive operations are marked as such for MCP clients; the CLI asks for
  confirmation on a terminal.
- Review the agent's reasons (`comments`, `selection_criteria`) rather than
  only its counts; the *Decisions* summary in `reviews_overview` shows how
  many studies each reviewer decided at each stage.
- Nothing leaves your instance, except with *Exclude/Include with AI*, which sends
  what the run's request says about each study (by default its title, keywords
  and abstract) to Jev (TypeSafe) with the caller's key. Otherwise the agent reads abstracts (and the PDFs you uploaded) from your
  instance and writes decisions back to it. PDFs stay in the data directory, or
  in your own bucket when the instance is configured with one.
