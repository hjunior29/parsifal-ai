# 04 — The Review Workflow

How a researcher uses Parsifal today, step by step, with the code that
implements each step and the guideline section it comes from
(K = Kitchenham & Charters 2007, section numbers as in the guidelines).
Endpoint details are in [06-http-endpoints.md](06-http-endpoints.md).

```
 Review ──► Planning ──────────────► Conducting ─────────────────────────► Reporting
 create     protocol                 search strings per source            export .docx
 title      objective, PICOC         import studies (BibTeX / Scopus)     export .xls
 descr.     research questions       study selection (A / R / D)
            keywords + synonyms      duplicates
            generic search string    quality assessment (score, cut-off)
            sources                  data extraction (final selection)
            inclusion/exclusion      data analysis (charts)
            QA checklist
            extraction form
```

## 0. Create a review

- UI: `/reviews/new/` (`reviews.views.new`) — `title`, `description`.
- Slug `name` generated from the title; unique per author. The review URL is
  `/<username>/<name>/`.
- The creator is `author`; co-authors join through invites
  (`/<u>/<r>/settings/invites/`), K 5.4 "study selection procedures — how many
  assessors".
- Review overview page (`reviews/review.html`) edits title/description;
  settings page renames the slug, transfers ownership, deletes.

## 1. Planning — build the protocol (K 5)

Page `/<u>/<r>/planning/protocol/` (`planning/protocol.html`), sections
saved independently via AJAX:

| Step | Guideline | UI / code | Stored as |
|------|-----------|-----------|-----------|
| 1.1 Objective | K 5.4 "Background / rationale" | `save_objective` (≤1000 chars) | `Review.objective` |
| 1.2 PICOC | K 5.3.2 question structure (Population, Intervention, Comparison, Outcome, Context) | `save_picoc` | `Review.population…context` |
| 1.3 Research questions | K 5.3 | `save_question`, `save_question_order`, `remove_question` | `Question` |
| 1.4 Keywords and synonyms | K 6.1.1 "derive major terms from the questions… identify synonyms… use Boolean OR/AND" | `import_pico_keywords` (split PICO fields on commas), `add_keyword`/`edit_keyword` with synonym formset | `Keyword` (+ `synonym_of`) |
| 1.5 Generic search string | K 6.1.1 | `generate_search_string` builds `("k" OR "s") AND (…)` per PICO group; user edits and `save_generic_search_string` | `SearchSession(source=None)` |
| 1.6 Sources | K 6.1.1 resources, 6.1.4 "rationale for the digital libraries" | `suggested_sources` + `add_suggested_sources` (7 defaults) or `save_source` (custom name/url); `remove_source` | `Review.sources` |
| 1.7 Selection criteria | K 6.2.1 inclusion/exclusion criteria | `add_criteria` (`I`/`E`), `remove_criteria` | `SelectionCriteria` |

Page `/<u>/<r>/planning/quality/` (`quality_assessment_checklist.html`):

| Step | Guideline | UI / code | Stored as |
|------|-----------|-----------|-----------|
| 1.8 QA questions | K 6.3.2 development of quality instruments (checklists; Tables 5–6) | `save_quality_assessment_question`, order, remove | `QualityQuestion` |
| 1.9 QA answers with weights | K 6.3.3 "using the quality instrument" (Y/P/N scoring, cf. Appendix 3: Y=1, P=0.5, N=0) | `save_quality_assessment_answer`, `add_suggested_answer` | `QualityAnswer` |
| 1.10 Cut-off score | K 6.3.3 (quality as inclusion threshold) | `calculate_max_score` (= #questions × max weight), `save_cutoff_score` | `Review.quality_assessment_cutoff_score` |

Page `/<u>/<r>/planning/extraction/` (`data_extraction_form.html`):

| Step | Guideline | UI / code | Stored as |
|------|-----------|-----------|-----------|
| 1.11 Data extraction form | K 6.4.1–6.4.2 "forms must collect all information needed to address the review questions"; electronic forms | `save_data_extraction_field` with type (boolean, string, float, integer, date, select-one, select-many) and lookup values; order; remove | `DataExtractionField`, `DataExtractionLookup` |

What K 5.4 lists for a protocol but Parsifal does **not** model: study
selection *procedures* (number of assessors, disagreement resolution), data
*synthesis* strategy, dissemination strategy, timetable, protocol evaluation
(K 5.5). See [10-methodology.md](10-methodology.md).

## 2. Conducting (K 6)

Each conducting page lists unmet prerequisites (`steps_messages`) and only
shows its tool when all are met.

### 2.1 Search — `/<u>/<r>/conducting/search/`

- Add a search-string slot per source (`add_source_string`), copy the generic
  string (`import_base_string`), adapt and save (`save_source_string`).
- For a source named *Scopus* and when `ELSEVIER_API_KEY` is set: run the
  query against the Scopus API (`search_scopus`), browse results and push them
  into the review (JS → `import_bibtex_raw_content`).
- K 6.1.4 (document the search: date, years covered, unfiltered results) is
  **not** captured — only the final string per source.

### 2.2 Import studies — `/<u>/<r>/conducting/import/`

- Upload a `.bib`/`.bibtex` per source (`import_bibtex`) or paste raw BibTeX
  (`import_bibtex_raw_content`). Field mapping in
  [07-import-export.md](07-import-export.md). Each entry becomes an `Article`
  with `status = U` (unclassified) and `created_by` the importer.
- Count per source shown on the page; `export_results` downloads all articles
  as `.xls`.

### 2.3 Study selection — `/<u>/<r>/conducting/studies/`

K 6.2.2 "study selection process": multi-stage, titles/abstracts first then
full text; K 6.2.3 reliability with two assessors.

- Tabs per source list articles (`source_articles`); clicking opens a modal
  (`article_details`) with the full record, `status`, `selection_criteria`
  (reason) and `comments`; keyboard navigation through the list.
- Save: `save_article_details` (whole form, including bibliographic edits).
- Bulk: select rows → accept / reject / unclassify / mark duplicated / remove
  (`multiple_articles_action_*`).
- Duplicates: `find_duplicates` groups non-duplicated articles by slugified
  title; `resolve_duplicated` marks one; `resolve_all` keeps the first of each
  group.
- Manual add: `new_article` + `save_article_details(article-id=None)`.
- Single consolidated decision per article (`Article.status`) — **no
  per-reviewer decisions and no agreement statistics** (K 6.2.3 Kappa).

### 2.4 Quality assessment — `/<u>/<r>/conducting/quality/`

Prerequisites: sources, imported articles, ≥1 accepted article, QA questions
and answers.

- Per accepted article, a table question × answer (`build_quality_assessment_table`);
  clicking an answer calls `save_quality_assessment` and returns the new
  score (Σ weights). Ordering by title/year kept in session.
- Summary tab (`quality_assessment_summary`).
- The score feeds the **final selection**: accepted articles with
  `score > cutoff` when a checklist exists and `cutoff > 0`
  (`Review.get_final_selection_articles`).
- `QualityAssessment.user` is never recorded (K 6.3.3 recommends ≥2 assessors
  or test–retest).

### 2.5 Data extraction — `/<u>/<r>/conducting/extraction/`

Prerequisites: sources, articles, ≥1 accepted article, ≥1 extraction field.

- For each final-selection article, one panel with one input per field
  (`build_data_extraction_table`); each change posts `save_data_extraction`
  (typed coercion in `DataExtraction.set_value`); "mark as done" toggles
  `finished_data_extraction` (`save_data_extraction_status`). Tabs
  todo/done/all.
- `export_data_extraction` → `.xls` matrix article × field.
- K 6.4.2 standard items (reviewer name, extraction date, notes) are not
  captured; `DataExtraction.user` is never set.

### 2.6 Data analysis — `/<u>/<r>/conducting/analysis/`

Two client-rendered charts fed by text endpoints:
`articles_selection_chart` (per source: imported vs accepted) and
`articles_per_year` (final selection by `year`). K 6.5 data synthesis
(descriptive tables, forest plots, qualitative synthesis) is otherwise
absent.

## 3. Reporting (K 7)

Page `/<u>/<r>/reporting/export/` lets the user tick sections and
`download_docx` renders them (`reporting/export.py`). Content exists for
planning sections and for conducting search strings / import counts; the
"Quality Assessment", "Data Extraction" and "Data Analysis" sections are
headings only. K 7.2 (Table 9 report structure: background, review
questions, methods, included/excluded studies, results, discussion,
conclusions) is only partially covered.

## 4. Where an AI agent would act (preview)

Every step above is a data operation on the review aggregate; none depends on
the browser. The API/CLI/MCP layer ([11-system-design.md](11-system-design.md))
exposes them so an agent can: draft the protocol from an objective; propose
keywords/synonyms and the search string; import search results; screen
titles/abstracts and record decisions **as its own user** (so the human can
review agreement); fill quality assessments and extraction forms; and read
analytics to draft the report. The engine that orchestrates this is out of
scope here; the data model additions it needs are listed in
[10-methodology.md](10-methodology.md) §4 and [12-roadmap.md](12-roadmap.md)
phase 8.
