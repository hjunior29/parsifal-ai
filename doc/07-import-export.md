# 07 — Import, Export and External Search

## BibTeX import into a review (`reviews.conducting`)

Two entry points, both `POST`, both redirecting back to the Import Studies
page with flash messages:

| Endpoint | Input | Parser |
|----------|-------|--------|
| `/reviews/conducting/import/bibtex_file/` (`import_bibtex`) | multipart `bibtex` file; accepted if extension is `.bib`/`.bibtex` or content type `application/x-bibtex` | `bibtexparser.load(file, BibTexParser(common_strings=True))` |
| `/reviews/conducting/import/bibtex_raw_content/` (`import_bibtex_raw_content`) | form field `bibtex_file` with raw BibTeX text | `bibtexparser.loads(text, ...)` |

Both call `bibtex_to_article_object(bib_database, review, source)` then
`_import_articles(request, source, articles)`, which saves each `Article`
individually (`created_by = request.user`), counting successes and failures.
Duplicates are **not** detected at import time; the user runs "find
duplicates" later.

### Field mapping (BibTeX entry → `reviews.Article`)

| BibTeX key (bibtexparser lower-cased) | Article field | Truncation |
|---------------------------------------|---------------|------------|
| `id` (entry key) | `bibtex_key` | 100 |
| `title` | `title` | 1000 |
| `journal` | `journal` | 1000 |
| `year` | `year` | 10 |
| `author` | `author` | 1000 |
| `abstract` | `abstract` | 4000 |
| `pages` | `pages` | 20 |
| `volume` | `volume` | 100 |
| `type`, else `document_type` | `document_type` | 100 |
| `doi` | `doi` | 50 |
| `link`, else `url` | `url` | 500 |
| `affiliation` | `affiliation` | 500 |
| `author_keywords` | `author_keywords` | 500 |
| `keywords`, else `keyword` | `keywords` | 500 |
| `publisher` | `publisher` | 100 |
| `issn` | `issn` | 50 |
| `language` | `language` | 50 |
| `note` | `note` | 500 |

Not imported: `booktitle`, `number`, `month`, `isbn`, `editor`, `series`,
`address`, `school`, `institution` and the BibTeX entry type
(`ENTRYTYPE`). Scopus exports use `document_type`, `author_keywords`,
`affiliation`, `link` — which is why those aliases exist.

Observed behaviour to preserve or improve in the API:

- Silent truncation to field sizes.
- Any exception while mapping one entry skips that entry (`continue`).
- No de-duplication against existing articles.
- `source` is mandatory: the UI only allows importing into a source already
  attached to the review.

## BibTeX import into the library (`library.views.import_bibtex`)

Same parser with `customization = convert_to_unicode`, mapping every standard
BibTeX field onto `library.Document` (`entry_type` from `type`, `author` from
`authors`/`author`, `address` from `address`/`correspondence_address1`,
`keywords` from `author_keywords`/`keywords`, `publication_type` from
`document_type`/`publication_type`, `url` from `url`/`link`). Saved in one
`transaction.atomic()` block, optionally added to a folder
(`add-to-folder-id`).

## Manual article entry

`save_article_details` with `article-id = "None"` creates an `Article` for the
given `review-id`/`source-id` from the full form (same fields as the mapping
above plus `comments`, `status`, `selection_criteria`). The same endpoint
edits existing articles.

## Elsevier / Scopus search

`parsifal/utils/elsevier/client.py` — `ElsevierClient(api_key, host="http://api.elsevier.com/content")`:

- `search_scopus(params)` → `GET /search/scopus?query=&count=&start=&apiKey=`
- `search_science_direct(params)` → `GET /search/scidir` (the view for it
  raises `Http404`; disabled upstream).
- Status 400 → `ElsevierInvalidRequest`; 429 → `ElsevierQuotaExceeded`;
  other non-200 → returns `None`.

`conducting.views.search_scopus` (GET: `query`, `count=25`, `start=0`)
proxies the JSON back to the browser; the JS renders results and lets the user
push them into the review through `import_bibtex_raw_content`. Requires
`ELSEVIER_API_KEY` (per-instance key, quota shared by all users). The host is
plain `http://`.

## Exports

### Study list — XLS (`conducting.views.export_results`, POST `review-id`)

`xlwt` workbook, sheet "Articles", one row per article of the review (all
statuses), columns in order:

`bibtex_key, title, author, journal, year, source, pages, volume, abstract,
document_type, doi, url, affiliation, author_keywords, keywords, publisher,
issn, language, note, selection_criteria, created_at, updated_at, created_by,
updated_by, status, comments`

Timestamps are written naive (`replace(tzinfo=None)`); `status` is the display
label. File name `articles.xls` (legacy BIFF format, 65 536-row limit).

### Data extraction — XLS (`conducting.views.export_data_extraction`, POST `review-id`)

One row per **final-selection** article (`get_final_selection_articles()`),
first column `article` (title), then one column per `DataExtractionField`
in order. Values: dates as `MM/DD/YYYY`, select-one as the lookup value,
select-many joined with `", "`, others raw `value`. File `data_extraction.xls`.

### Protocol report — DOCX (`reporting.views.download_docx`, GET `review-id`, `export[]`)

`reporting/export.py: export_review_to_docx(review, sections)` builds a
python-docx document. `sections` is the list of checkbox names from
`reporting/export.html`; headings "Planning" and "Conducting" are always added.

| Section key | Content |
|-------------|---------|
| `name` | Title (H1, centred) |
| `authors` | Author + co-author screen names |
| `description` | Review description |
| (always) | Objective paragraph under "Planning" if set |
| `picoc` | Bulleted Population/Intervention/Comparison/Outcome/Context |
| `research_questions` | Numbered list |
| `keywords_synonyms` | Two-column table keyword → synonyms |
| `search_string` | Generic search string |
| `sources` | Bulleted `name (url)` |
| `selection_criteria` | Inclusion and exclusion lists |
| `quality_assessment_checklist` | Questions and answers lists |
| `data_extraction_form` | Field descriptions |
| `source_search_strings` | Per-source search strings |
| `number_imported_studies` | Count per source |
| `quality_assessment`, `data_extraction`, `data_analysis` | **Heading only — no content generated** |

File name `<review.name>.docx`.

## Implications for the fork

- The API should expose import as `POST /reviews/{id}/sources/{id}/articles:import`
  accepting raw BibTeX text (what agents will have) and return per-entry
  results instead of flash messages.
- Exports should be available as downloadable resources and, more usefully for
  agents, as **JSON/CSV equivalents** of the XLS sheets.
- `xlwt` (.xls) should be replaced by `openpyxl` (.xlsx) or CSV when touched.
- The DOCX report's empty sections are the natural place for the AI harness to
  inject synthesis text later; keep `export_review_to_docx` as the single
  rendering function and extend `sections` rather than forking it.
