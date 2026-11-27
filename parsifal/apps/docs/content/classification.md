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
results (`source document-search …`; the date is also on *Import Studies* and
in `article import --searched-at`). Imported articles keep a link to that
documented search. Both guidelines ask for this table in the report.

A **test set of known papers** evaluates the search: add the titles (and DOIs)
of papers you know must be found (`test-set add`); Parsifal matches them
against the imported articles and reports the recall (`test-set get`).

## Classifying the studies

A study is classified with the **data extraction form**, like everything else
extracted from it: a **single choice** or **multiple choice** field per scheme,
its categories as the options. The scheme may be one of the usual ones or
emerge while reading the studies (add the option to the field when a study calls
for one).
Usual schemes:

| Scheme | Categories |
|--------|------------|
| Research type (Wieringa et al.) | Evaluation research, Validation research, Solution proposal, Philosophical paper, Experience paper, Opinion paper |
| Contribution type | Process, Method, Model, Tool, Metric, Other |
| Research method | Case study, Experiment, Survey, Action research, Grounded theory, Design science, Literature review, Other / none |
| Venue type | Journal, Conference, Workshop, Book chapter, Thesis, Technical report, Other |
| Study focus | Academic, Industrial, Government, Open source, Other |

Each value carries its evidence, as every extracted value does. *Data
Analysis* counts the studies of the final selection per option; the extraction
export (one row per study, one column per field) holds what a bubble plot of
two schemes needs, drawn with the tool of your choice.

## Process checklist

Petersen et al. list 26 actions that strengthen a mapping study (motivate the
need, snowballing, test set, additional reviewer, research-type
classification, validity discussion…). `checklist get` shows them;
`checklist set --key search_database --applied --notes "Scopus, IEEE"` records
what you did. The applied ratio appears in the review overview and the report.

## Report

The DOCX report (**Reporting → Export**) can include the review type, the three
protocol texts, the search documentation table, the known-paper recall and the process checklist; its
quality assessment, data extraction and analysis sections carry tables.

## Where to find these in the interface

The test set, the search documentation and the process checklist are
available through the API, the CLI and the MCP tools; the web pages expose the
review type, the report sections and the reviewer agreement panel. Studies are
classified on *Data Extraction*, with the choice fields of the form.

## In the API, the CLI and the MCP server

| Task | CLI command | API endpoint |
|------|-------------|--------------|
| Update protocol texts | `parsifal review update --review R --selection-procedure … --synthesis-strategy … --validity-threats …` | `PATCH /api/v1/reviews/{id}` |
| Document a source search | `parsifal source document-search --review R --source-id S --searched-at YYYY-MM-DD` | `PUT /api/v1/reviews/{id}/sources/{source_id}/search` |
| Manage known-paper test set | `parsifal test-set add --review R …` · `parsifal test-set get --review R` | `GET` / `POST /api/v1/reviews/{id}/test-set` |
| A classification scheme | `parsifal extraction field create --review R --description "Research type" --field-type O --lookup-values …` (`M` for several per study) | `POST /api/v1/reviews/{id}/extraction/fields` |
| Classify a study | `parsifal extraction set --review R --article A --field-id F --value … --evidence …` | `PUT /api/v1/reviews/{id}/articles/{article_id}/extraction` |
| Studies per option | `parsifal analytics extraction --review R` | `GET /api/v1/reviews/{id}/analytics/extraction` |
| Petersen process checklist | `parsifal checklist get --review R` · `parsifal checklist set --review R --key search_database --applied --notes "Scopus, IEEE"` | `GET /api/v1/reviews/{id}/checklist` · `PUT …/checklist/{key}` |
