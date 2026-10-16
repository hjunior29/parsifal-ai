# Classification, search evaluation and checklist (optional steps)

Parsifal has **one review workflow**. The features on this page are optional
steps any review can use; a **systematic mapping study** (Petersen, Vakkalanka
& Kuzniarz, 2015) is simply a review that uses most of them and usually skips
the quality assessment — it is not a separate mode.

## Review type

Choose *Systematic literature review* or *Systematic mapping study* when
creating a review or in **Review settings**. The type is a label: it is shown
next to the title and in the review lists, and selects the vocabulary and
section set of the report. Nothing else changes.

Three protocol texts are available to every review and appear in the report:
the **study selection procedure** (assessors, decision rules), the **synthesis
strategy** and the **validity threats** (descriptive, theoretical,
generalisability, interpretive validity, repeatability). They are edited
through the API/CLI (`review update --selection-procedure … --synthesis-strategy …
--validity-threats …`).

## Documenting and evaluating the search

For each source you can record how the search was run — `database`,
`snowballing` or `manual` — the date, the years covered and the number of
results (`source document-search …`). Imported articles keep a link to that
documented search. Both guidelines ask for this table in the report.

A **test set of known papers** evaluates the search: add the titles (and DOIs)
of papers you know must be found (`test-set add`); Parsifal matches them
against the imported articles and reports the recall (`test-set get`).

## Classification facets

Classifying studies along **facets** complements (or, in a mapping study,
replaces) data extraction. A facet is a question answered for every included
study by picking one or more categories:

| Template | Categories |
|----------|------------|
| Research type (Wieringa et al.) | Evaluation research, Validation research, Solution proposal, Philosophical paper, Experience paper, Opinion paper |
| Contribution type | Process, Method, Model, Tool, Metric, Other |
| Research method | Case study, Experiment, Survey, Action research, Grounded theory, Design science, Literature review, Other / none |
| Venue type | Journal, Conference, Workshop, Book chapter, Thesis, Technical report, Other |
| Study focus | Academic, Industrial, Government, Open source, Other |

Create facets from these templates (`facet create --template research_type`)
or define your own **emerging** scheme built while reading the abstracts
(`facet create --name Topic --multiple --categories …`); categories can be
added and reordered as the scheme evolves. A facet is single-choice or accepts
several categories per study. Classify a study per facet
(`classification set --article A --facet-id F --category-ids …`); each
classification records who made it and optional notes.

Analysis:

- `analytics facet-frequencies --facet F` — studies per category.
- `analytics facet-matrix --rows F1 --columns F2` — counts for every pair of
  categories of two facets: the data behind a **bubble plot** (for example
  topic × research type), which shows where research accumulates and where the
  gaps are.

Both consider the final selection only. Export the JSON and draw the plots with
the tool of your choice.

## Process checklist

Petersen et al. list 26 actions that strengthen a mapping study (motivate the
need, snowballing, test set, additional reviewer, research-type
classification, validity discussion…). `checklist get` shows them;
`checklist set --key search_database --applied --notes "Scopus, IEEE"` records
what you did. The applied ratio appears in the review overview and the report.

## Report

The DOCX report (**Reporting → Export**) can include the review type, the three
protocol texts, the classification scheme and its results, the search
documentation table, the known-paper recall and the process checklist; its
quality assessment, data extraction and analysis sections carry tables.

## Where to find these in the interface

Today these steps are available through the API, the CLI and the MCP tools;
the web pages expose the review type, the report sections and the reviewer
agreement panel. Screens for facets and classification are planned next to the
data extraction form.
