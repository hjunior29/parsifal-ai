# Multiple reviewers and agreement

Both guidelines recommend that at least two people screen the studies
independently and that the agreement between them is measured and reported
(Kitchenham & Charters §6.2.3; Petersen et al. §5.1.2). In this fork a reviewer
can be a colleague or an AI agent with its own account.

## Decisions versus status

- The **status** of an article (unclassified, accepted, rejected, duplicated)
  is the consolidated outcome — what the study selection page shows and what
  the final selection uses.
- A **decision** is one reviewer's judgement about one article at one
  **stage** — `title_abstract` or `full_text`; a rapid review starts with a
  `title` round ([Rapid reviews](/docs/rapid-review/)) — with the selection
  criterion used as reason and a comment. Left out, the stage is the review's
  first round. Recording a decision never changes the status, except in the
  round mode of a rapid review, where a status given at a round is also the
  reviewer's decision there.

Decisions are recorded through the API, CLI and MCP:

| Task | CLI command | API endpoint |
|------|-------------|--------------|
| Record acceptance | `parsifal decision record --review R --ids 12 --ids 15 --status A --selection-criteria-id 3 --comments "empirical, in scope"` | `POST /api/v1/reviews/{id}/decisions` |
| Record rejection at a stage | `parsifal decision record --review R --ids 13 --status R --selection-criteria-id 4 --stage title_abstract` | `POST /api/v1/reviews/{id}/decisions` |
| List decisions by reviewer | `parsifal decision list --review R --stage title_abstract --user-id 7` | `GET /api/v1/reviews/{id}/decisions` |
| View all decisions for one study | `parsifal decision article --review R --article 13` | `GET /api/v1/reviews/{id}/articles/{article_id}/decisions` |

## Measuring agreement

| Task | CLI command | API endpoint |
|------|-------------|--------------|
| Kappa (first two reviewers) | `parsifal decision agreement --review R` | `GET /api/v1/reviews/{id}/decisions/agreement` |
| Kappa for a specific pair & stage | `parsifal decision agreement --review R --user-a-id 2 --user-b-id 7 --stage full_text` | `GET /api/v1/reviews/{id}/decisions/agreement?user_a_id=&user_b_id=&stage=` |
| Disagreements across all reviewers | `parsifal decision disagreements --review R` | `GET /api/v1/reviews/{id}/decisions/disagreements` |
| Disagreements between two reviewers | `parsifal decision disagreements --review R --user-a-id 2 --user-b-id 7` | `GET /api/v1/reviews/{id}/decisions/disagreements?user_a_id=&user_b_id=` |

The agreement report gives the number of studies both reviewers decided,
the percent agreement, **Cohen's kappa** and its usual interpretation (Landis &
Koch: slight, fair, moderate, substantial, almost perfect). Report the initial
kappa, discuss the disagreements and resolve them — the guidelines ask for
exactly this.

On the web, **Reviewer agreement** (Conducting → Study Selection) shows the
same report for **two reviewers at a time**, the first two by default: with
three or more, choose who to compare in *Compare … with …* (kappa compares a
pair, so always two different reviewers). The disagreements listed are where
those two differ, and consolidating there uses their decisions only. Click a
study in its list of disagreements to open its details
and read it; its *Reviewers* tab has every reviewer's decision and comment. Set
the status there, and **Back to agreement** returns to the list. `decision disagreements`
returns each study in full (with its id), so `decision article --article ID`
does the same from the CLI.

To find a study in the list, the search box next to *Action* filters it by
title, DOI or BibTeX key (`article list --q` in the CLI, `q` in the API).

## Consolidating

| Task | CLI command | API endpoint |
|------|-------------|--------------|
| Consolidate with unanimous rule | `parsifal decision consolidate --review R --rule unanimous` | `POST /api/v1/reviews/{id}/decisions/consolidate` |
| Consolidate specific studies (`any_include`) | `parsifal decision consolidate --review R --rule any_include --ids 13 --ids 14` | `POST /api/v1/reviews/{id}/decisions/consolidate` |
| Consolidate at `full_text` (`majority`) | `parsifal decision consolidate --review R --rule majority --stage full_text` | `POST /api/v1/reviews/{id}/decisions/consolidate` |
| Consolidate using two reviewers only | `parsifal decision consolidate --review R --rule unanimous --user-ids 2 --user-ids 7` | `POST /api/v1/reviews/{id}/decisions/consolidate` |

| Rule | Outcome |
|------|---------|
| `unanimous` | Status set only where all reviewers agree. |
| `any_include` | Accepted if any reviewer accepts (studies pass to the next stage); otherwise set only when unanimous. |
| `majority` | Strict majority; ties stay unresolved. |

Unresolved studies keep their current status and are listed in the response so
you can settle them in a consensus meeting (then set the status in the UI or
with `article set-status`). Write the rule you used in the protocol's
*selection procedure*.

Consolidating sets the studies' status and records you as the one who set it;
it never changes the decisions, which are each reviewer's record and the basis
of the kappa. So a disagreement stays in the list after it is settled. The
list's *Status now* column (and `article.status` / `article.updated_by` in
`decision disagreements`) shows where each one stands, and the line above it
counts who set those statuses — you, after a consolidation, or the AI reviewer
whose run set them. The response says how many studies the rule decided and
how many of them actually **changed** status (`changed`, `changed_ids`); the
window keeps the rule you used last in that review.

To screen again from the start (for instance with another request to Jev),
*Review settings → Danger zone → Reset the study selection* puts every study
except duplicates back to unclassified and deletes the decisions of the
reviewers you choose; see [Exclude, include and screen with AI](/docs/ai-screening/).

## Where else the reviewer is recorded

Quality assessment answers and extracted values store the user who entered
them, so an agent's work can always be told apart from a human's, even where
there is a single consolidated value.
