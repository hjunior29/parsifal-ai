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
parsifal decision disagreements --review R
```

The agreement report gives the number of studies both reviewers decided,
the percent agreement, **Cohen's kappa** and its usual interpretation (Landis &
Koch: slight, fair, moderate, substantial, almost perfect). Report the initial
kappa, discuss the disagreements and resolve them — the guidelines ask for
exactly this.

On the web, **Reviewer agreement** (Conducting → Study Selection) shows the
same report. Click a study in its list of disagreements to open its details
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

## Where else the reviewer is recorded

Quality assessment answers, extracted values and classifications store the
user who entered them, so an agent's work can always be told apart from a
human's, even where there is a single consolidated value.
