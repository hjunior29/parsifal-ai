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
  **stage** — `title_abstract` or `full_text` — with the selection criterion
  used as reason and a comment. Recording a decision never changes the status.

Decisions are recorded through the API/CLI/MCP:

```bash
parsifal decision record --review R --ids 12 --ids 15 --status A --selection-criteria-id 3 --comments "empirical, in scope"
parsifal decision record --review R --ids 13 --status R --selection-criteria-id 4 --stage title_abstract
parsifal decision list --review R --stage title_abstract --user-id 7
parsifal decision article --review R --article 13          # every reviewer's decision for one study
```

## Measuring agreement

```bash
parsifal decision agreement --review R                      # first two reviewers at title_abstract
parsifal decision agreement --review R --user-a-id 2 --user-b-id 7 --stage full_text
parsifal decision disagreements --review R                  # among every reviewer
parsifal decision disagreements --review R --user-a-id 2 --user-b-id 7   # where those two differ
```

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

```bash
parsifal decision consolidate --review R --rule unanimous
parsifal decision consolidate --review R --rule any_include --ids 13 --ids 14
parsifal decision consolidate --review R --rule majority --stage full_text
parsifal decision consolidate --review R --rule unanimous --user-ids 2 --user-ids 7   # those two reviewers only
```

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

Quality assessment answers, extracted values and classifications store the
user who entered them, so an agent's work can always be told apart from a
human's, even where there is a single consolidated value.
