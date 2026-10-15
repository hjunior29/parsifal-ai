# Systematic mapping studies

A **systematic mapping study** (Petersen, Vakkalanka & Kuzniarz, 2015) gives an
overview of a research area — which topics, research types, methods and venues
exist and where the gaps are — rather than aggregating evidence for one narrow
question. Parsifal supports it alongside the classic systematic literature
review.

## Review type

Choose *Systematic mapping study* when creating a review or in **Review
settings**. The type is shown next to the review title and in the report.
Quality assessment is optional for maps: the final selection is simply the set
of accepted studies unless you define a checklist and a cut-off.

Three protocol texts complement the type: the **study selection procedure**
(assessors, decision rules), the **synthesis strategy** and the **validity
threats** (descriptive, theoretical, generalisability, interpretive validity,
repeatability). They are edited through the API/CLI (`review update
--selection-procedure … --synthesis-strategy … --validity-threats …`) and appear
in the report.

## Documenting the search

For each source you can record how the search was run — `database`,
`snowballing` or `manual` — the date, the years covered and the number of
results (`source document-search …`). Imported articles keep a link to that
documented search.

A **test set of known papers** evaluates the search: add the titles (and DOIs)
of papers you know must be found (`test-set add`); Parsifal matches them
against the imported articles and reports the recall (`test-set get`).

## Classification scheme

Mapping studies classify every included study along several **facets**:

| Template | Categories |
|----------|------------|
| Research type (Wieringa et al.) | Evaluation research, Validation research, Solution proposal, Philosophical paper, Experience paper, Opinion paper |
| Contribution type | Process, Method, Model, Tool, Metric, Other |
| Research method | Case study, Experiment, Survey, Action research, Grounded theory, Design science, Literature review, Other / none |
| Venue type | Journal, Conference, Workshop, Book chapter, Thesis, Technical report, Other |
| Study focus | Academic, Industrial, Government, Open source, Other |

Create facets from these templates (`facet create --template research_type`)
or define your own **emerging** scheme built during keywording of the
abstracts (`facet create --name Topic --multiple --categories …`); categories
can be added and reordered as the scheme evolves. A facet is single-choice or
accepts several categories per study.

Classify a study per facet (`classification set --article A --facet-id F
--category-ids …`); each classification records who made it and optional
notes.

## Analysis

- `analytics facet-frequencies --facet F` — studies per category of a facet.
- `analytics facet-matrix --rows F1 --columns F2` — counts for every pair of
  categories of two facets: the data behind a **bubble plot** (for example
  topic × research type).

Both consider the final selection only. Export them as JSON and draw the plots
with the tool of your choice.

## Process checklist

Petersen et al. list 26 actions that strengthen a mapping study (motivate the
need, snowballing, test set, additional reviewer, research-type
classification, validity discussion…). `checklist get` shows them;
`checklist set --key search_database --applied --notes "Scopus, IEEE"` records
what you did. The applied ratio appears in the review overview and the report.

## Report

The DOCX report (**Reporting → Export**) gained sections for the review type,
the three protocol texts, the classification scheme and its results, the
search documentation table, the known-paper recall and the process checklist,
and its quality assessment, data extraction and analysis sections now carry
tables instead of empty headings.
