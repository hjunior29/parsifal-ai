# 13 — Known Issues and Technical Debt

Observed while reading the inherited code (upstream 2.2.1). Items are grouped
by how they affect the fork. None of these were fixed as part of writing this
documentation; the roadmap schedules them.

## A. Bugs

| # | Where | Problem | Fix |
|---|-------|---------|-----|
| A1 | `accounts/views.py` `upload_picture`, `save_uploaded_picture` | **Fixed in phase 0.** Two independent breakages: `Image.ANTIALIAS` was removed in Pillow 10, and `FileSystemStorage.save()` was called with an absolute path, which Django ≥ 3.2 rejects with `SuspiciousFileOperation`. Profile picture upload had been broken upstream since those upgrades. | Storage-relative names + `fs.path()`, `Image.LANCZOS`, JPEG conversion; covered by `accounts/tests/test_upload_picture_view.py`. |
| A2 | `conducting/views.py` `articles_selection_chart`, `articles_per_year` | **Fixed in phase 0.** No `login_required`/`author_required`: anyone could read per-source and per-year counts of any review by id. | Guards added; covered by `conducting/tests/test_analytics_views.py`. |
| A3 | `conducting/views.py` `search_science_direct` | Always `Http404` while the UI still offers it for a `Science@Direct` source. | Remove the UI affordance or re-enable. |
| A4 | `reviews/models.py` `Article.year` is `CharField` | **Fixed in phase 2.** `Article.year_int` (parsed from `year` on save) backs `analytics.final_selection_by_year`; unknown years are reported as `None`. | — |
| A5 | `DataExtraction._set_select_many_value` | **Addressed in phase 2.** `services.extraction.set_value` has set semantics (`values=[...]`); the legacy UI keeps toggling through `toggle_select_value`. | — |
| A8 | `conducting/views.py` BibTeX import (upstream) | **Fixed in phase 2.** Upstream read `entry["id"]`/`entry["type"]`, but bibtexparser exposes them as `ID`/`ENTRYTYPE`, so `bibtex_key` was never stored and `document_type` only came from Scopus' `document_type` field. | `services.studies.BIBTEX_FIELD_ALIASES`. |
| A6 | `.env.example` `EMAIL_BACKEND` | Listed but never read by settings; local uses console, production SMTP. | Read it with `config()` with a sensible default. |
| A7 | `base.py` `LOCALE_PATHS` | Points to `parsifal/locale` which does not exist; pt-br advertised but absent. | Drop `pt-br` or add translations. |

## B. Authorization gaps (must not be replicated by the API)

**Fixed.** Upstream, `author_required` validated only the **review**, and the
views then loaded other objects by primary key with no review filter, so a
member of review X could act on review Y's objects by guessing ids. Since then:

- `author_required` / `main_author_required` resolve the review once and set
  `request.review`; the views use it. `review-id` comes from the body for a
  POST and from the query string otherwise; a request naming two different
  reviews is refused (400), an unknown review is 404.
- Every child object in the Planning views is looked up through the review
  (`review.research_questions`, `review.keywords`, `review.sources`,
  `review.selectioncriteria_set`, `review.qualityquestion_set`,
  `review.qualityanswer_set`, `review.dataextractionfield_set`); an id of
  another review is a 404/400 and nothing changes. Saving and removing sources
  go through `services.protocol` (default libraries cannot be edited; adding a
  suggested library accepts default libraries only).
- Conducting uses only the review's own sources (search strings, BibTeX
  import, new study) and selection criteria (study details).
- The library views filter folders and documents by `user`.

Covered by `planning/tests/test_views_security.py` and
`conducting/tests/test_views_scoping.py`.

Rule for the fork: every service function receives the `review` (already
authorised) and filters children with `review=review`; lookups across reviews
are impossible by construction.

## C. State-changing GET requests

**Fixed.** Every Planning view that changes something requires POST and the
JS sends the CSRF token (`save_source`, `remove_source`, `add_criteria`,
`remove_criteria`, `import_pico_keywords`, `remove_keyword`,
`remove_quality_assessment_question`, `remove_quality_assessment_answer`,
`add_suggested_answer`, `save_cutoff_score`, `remove_data_extraction_field`
were GETs). `follow`/`unfollow` no longer exist.

## D. Design debt that affects the API/service layer

| # | Issue | Consequence |
|---|-------|-------------|
| D1 | HTML built with string formatting inside views (`build_*_table`, `html_source`, `suggested_sources`, `add_suggested_answer`; names and urls are escaped). | Business logic and presentation are fused; the service layer must re-derive the data these functions compute (scores, lookups, selected answers). |
| D2 | `try: … except Exception: return HttpResponseBadRequest()` in ~50 views (planning views still; conducting action views now catch `DomainError` and return its message). | Services raise typed exceptions (`core/exceptions.py`); the API maps them to 4xx with messages. |
| D3 | Silent truncation (`[:1000]` etc.) on import and save. | API should validate lengths and report, or truncate explicitly with a warning field. |
| D4 | ~~No DB uniqueness for `QualityAssessment`, `DataExtraction`, `SearchSession`~~ | Fixed in phase 2 (`reviews.0038`, de-duplicates first). |
| D5 | `Source` is a global table; custom sources are deleted when detached. Default sources can no longer be edited (`services.protocol.update_source`). | Model per-review sources explicitly. |
| D6 | ~~`QualityAssessment.user` / `DataExtraction.user` never set; `StudySelection`/`Study`/`SearchResult` unused~~ | Fixed: services record the acting user (phase 2), unused models dropped and `StudyDecision` + agreement added (phase 8). |
| D7 | `Review.status`, `SearchSession.version`, `Question.parent_question`, `Document.review`, `Document.shared_folder`, `DocumentFile` exist without behaviour. | Still open for these; `SearchResult/StudySelection/Study` were removed in phase 8. |
| D8 | Keyword `related_to` covers P/I/C/O but PICOC has Context; `generate_search_string` ignores Context. | Add `X` (Context) choice or document the omission. |
| D9 | `search_studies` matches sources by **name** (`"Scopus"`, `"Science@Direct"`) to enable API search. | Replace with an explicit `Source.provider` field. |
| D10 | ~~`STATIC_ROOT`/`MEDIA_ROOT` default outside the repo~~ (phase 0: both under `PARSIFAL_DATA_DIR`); media paths derived from username (`profile_pictures/<username>.jpg`). | Renaming a user still orphans the picture. |
| D11 | `DATA_UPLOAD_MAX_MEMORY_SIZE` 10 MB applies to `import_bibtex_raw_content` (text in form body). | API import should accept files/streams or chunk. |
| D12 | DOCX export has empty sections for QA, data extraction, data analysis. | Natural extension point for synthesis output. |
| D13 | `xlwt` produces legacy `.xls`; `bibtexparser` 1.x is unmaintained (2.x has a new API). | Replace when touched: `openpyxl`/CSV, `bibtexparser>=2`. |
| D14 | Python 3.9 is end-of-life (Oct 2025); `black` target versions include py36; the Python `mcp` SDK requires ≥ 3.10. | ADR-005 (amended): minimum Python raised to 3.10 in phase 0. |

## E. Test and CI debt

- Planning views: authorization and the main actions are tested
  (`planning/tests/`); the library has service tests only (see
  [09-testing.md](09-testing.md)).
- ~~CI installs PostgreSQL only because of the default `DATABASE_URL`~~ — fixed in phase 0.
- ~~`codecov.yml` targets `master` only~~ — fixed in phase 0 (`master` and `dev`).
- ~~`tox.ini` `basepython = python3` with `py39` env name~~ — fixed in phase 0 (`py310`, `python3.10`).

## F. Security hardening for self-hosting

- `SECRET_KEY` default is a fixed string; `DEBUG` defaults to `True`;
  `ALLOWED_HOSTS` default localhost. The fork's `init` must generate a secret
  and write a production-ready `.env`.
- Elsevier host is `http://` (plaintext API key in query string).
- Invite landing page is public by design (masked e-mail); acceptable.
- No rate limiting on login; acceptable for a trusted network, document it.
