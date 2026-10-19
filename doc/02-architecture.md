# 02 — Architecture

## Shape of the system

Parsifal is a **single Django monolith** rendering server-side HTML. There is
no JSON API, no background worker, no message queue and no cache layer. The
only external service is the optional Elsevier (Scopus) search.

```
Browser (Bootstrap 3 + jQuery + Mustache)
   │  full-page GET/POST                       │  AJAX GET/POST (form-encoded)
   ▼                                           ▼
Django URL conf (parsifal/urls.py + per-app urls.py)
   │                                           │
   ├─ "page" views  ──► templates (HTML pages)  └─ "action" views ──► HTML fragments / text / JSON
   │                                                   │
   └──────────────── Django ORM (models.py per app) ───┘
                              │
                        PostgreSQL (upstream) / SQLite (fork)
                              │
                     files: <data dir>/files or an S3-compatible bucket (the studies' PDFs)
```

Everything that matters lives in the `reviews` app family
(`reviews`, `reviews.planning`, `reviews.conducting`, `reviews.reporting`,
`reviews.settings`). The other apps are account management and SaaS features
(see [05-apps-reference.md](05-apps-reference.md)).

## Two kinds of routes

### 1. Page routes — `/<username>/<review_name>/...`

Declared in `parsifal/urls.py`. They identify a review by the **author's
username and the review slug** (`Review.name`, unique per author). Examples:

| Path | View | Template |
|------|------|----------|
| `/<username>/` | `reviews.views.reviews` | `reviews/reviews.html` (a user's review list — this is the "profile" page) |
| `/<username>/<review_name>/` | `reviews.views.review` | `reviews/review.html` |
| `/<username>/<review_name>/planning/protocol/` | `planning.views.protocol` | `planning/protocol.html` |
| `/<username>/<review_name>/planning/quality/` | `planning.views.quality_assessment_checklist` | `planning/quality_assessment_checklist.html` |
| `/<username>/<review_name>/planning/extraction/` | `planning.views.data_extraction_form` | `planning/data_extraction_form.html` |
| `/<username>/<review_name>/conducting/search/` | `conducting.views.search_studies` | `conducting/conducting_search_studies.html` |
| `/<username>/<review_name>/conducting/import/` | `conducting.views.import_studies` | `conducting/conducting_import_studies.html` |
| `/<username>/<review_name>/conducting/studies/` | `conducting.views.study_selection` | `conducting/conducting_study_selection.html` |
| `/<username>/<review_name>/conducting/quality/` | `conducting.views.quality_assessment` | `conducting/conducting_quality_assessment.html` |
| `/<username>/<review_name>/conducting/extraction/` | `conducting.views.data_extraction` | `conducting/conducting_data_extraction.html` |
| `/<username>/<review_name>/conducting/analysis/` | `conducting.views.data_analysis` | `conducting/conducting_data_analysis.html` |
| `/<username>/<review_name>/reporting/export/` | `reporting.views.export` | `reporting/export.html` |
| `/<username>/<review_name>/settings/` | `settings.views.settings` | `settings/review_settings.html` |
| `/<username>/<review_name>/settings/invites/` | `invites.views.ManageAccessView` | `invites/manage_access.html` |

`/<username>/<review_name>/planning/`, `/conducting/` and `/reporting/`
redirect to the first tab of each phase.

Because `<username>/` is a catch-all at the end of `urlpatterns`, every
fixed prefix (`reviews/`, `library/`, `settings/`, `help/`, `blog/`,
`activity/`, `invites/`, `admin/`) must be declared before it — and a user
cannot have a username equal to one of those prefixes
(`authentication.validators.validate_forbidden_usernames`).

### 2. Action routes — `/reviews/planning/...`, `/reviews/conducting/...`

Declared in `reviews/urls.py` and included sub-`urls.py`. They do **not**
carry the review in the URL; instead every call sends `review-id` (and other
`*-id` fields) as a form parameter. The page embeds
`<input type="hidden" id="review-id" value="{{ review.id }}">`
(`reviews/review_header.html`) and each page-specific JS module reads it.

Responses are one of:

- an **HTML fragment** rendered from a `partial_*.html` template or built with
  Python string formatting inside the view (e.g. `build_quality_assessment_table`,
  `html_source`, `build_article_table_row`), which the JS injects into the DOM;
- **plain text** (a score, a search string, `"Source:count:accepted,..."`);
- occasionally **JSON** (`add_keyword`, `edit_keyword`, library folder/document views);
- a **redirect** with a Django `messages` flash (imports, source-string management);
- `HttpResponseBadRequest()` with an empty body on any exception (`try/except Exception`).

The complete inventory, with inputs and outputs, is in
[06-http-endpoints.md](06-http-endpoints.md). This inventory is the functional
contract that the fork's JSON API must cover.

## Authorization model

| Mechanism | Where | Rule |
|-----------|-------|------|
| `@login_required` | all page and action views (except a few — see known issues) | Anonymous → redirect to `/login/?next=...`. |
| `@author_required` (`reviews/decorators.py`) | most page/action views | If URL kwargs `username`+`review_name` exist: load review, allow if `review.is_author_or_coauthor(user)`, else **404**. Otherwise read `review-id` from POST then GET; allow if author/co-author, else **403**; missing id → 400. |
| `@main_author_required` | review settings, transfer, remove co-author | Same lookup, but only `review.author`. |
| `ReviewMixin` + `MainAuthorRequiredMixin` / `AuthorRequiredMixin` (`reviews/mixins.py`) | class-based views (`DeleteReviewView`, invites) | `review` cached property from URL kwargs; `UserPassesTestMixin` → 403. |
| `login_required` only | library, accounts, activities | Library lookups are scoped to `request.user` in every view since 2026-10-16 (before, only some were). |

Decorator order in the code is `@author_required` **outside**
`@login_required`, so for an anonymous user `author_required` runs first:
`is_author_or_coauthor(AnonymousUser)` is false → 404/403 instead of a login
redirect on action endpoints. Page routes return 404 for anonymous users for
the same reason.

Important for the fork: `author_required` only verifies the **review**. Many
action views then fetch secondary objects by primary key (`Question`,
`QualityQuestion`, `QualityAnswer`, `DataExtractionField`, `Article`) without
checking they belong to that review. The service layer must scope every lookup
by review (see [13-known-issues.md](13-known-issues.md)).

## Frontend contract

- Each page loads Bootstrap/jQuery from `parsifal/static/` and one or more
  page scripts from the app's `static/js/` (e.g. `planning_keyword.js`,
  `conducting_study_selection.js` — 521 lines, the largest).
- CSRF: scripts read `csrfmiddlewaretoken` from a form rendered on the page and
  post it as a form field. There is no global `$.ajaxSetup` header; several
  mutating endpoints are called with **GET** precisely to avoid CSRF handling
  (`save_source`, `remove_source`, `add_criteria`, `remove_criteria`,
  `remove_keyword`, `remove_quality_assessment_*`, `remove_data_extraction_field`,
  `save_cutoff_score`, `follow`, `unfollow`).
- Mustache templates are used in a few places for client-side rendering;
  `tablesorter` for sortable tables; `jquery.fileupload` for uploads;
  `Jcrop` for profile pictures.
- Study-selection UI: a modal shows one article at a time; keyboard shortcuts
  change status; each change POSTs `save_article_details` with the whole
  article form and receives the updated `<tr>`.
- Charts in Data Analysis are rendered client-side from the text responses of
  `articles_selection_chart` and `articles_per_year`.

## Settings, static and media

- Settings split described in [08-configuration-and-deployment.md](08-configuration-and-deployment.md).
- Static files: app-level `static/` + project `parsifal/static/`, collected to
  `STATIC_ROOT` (two directories above the repo by default), compressed by
  django-compressor when `COMPRESS_ENABLED`.
- Media: upstream kept profile pictures under `MEDIA_ROOT` (removed in the
  fork, and `/media/` is no longer served); `DocumentFile.document_file` exists
  but is not wired to any view.
- Uploaded files: the studies' PDFs go to the "files" storage
  (`STORAGES["files"]`: `<data dir>/files`, or an S3-compatible bucket), reached
  through `core.models.files_storage()`; see `services/full_texts.py`.

## Request lifecycle example — accepting a study

```mermaid
sequenceDiagram
    participant U as Browser (conducting_study_selection.js)
    participant V as conducting.views.save_article_details
    participant D as reviews.decorators.author_required
    participant M as reviews.models.Article
    U->>V: POST /reviews/conducting/save_article_details/ (review-id, article-id, status=A, criteria, ...)
    V->>D: wrap(request)
    D->>M: Review.objects.get(pk=review-id); is_author_or_coauthor(user)?
    D-->>V: ok (else 403)
    V->>M: Article.objects.get(pk=article-id, review_id=review-id)
    V->>M: assign all fields from POST, truncate, save(updated_by=user)
    V-->>U: 200 text/html "<tr oid=.. article-status=A>...</tr>"
    U->>U: replace table row, advance modal to next article
```

## Internationalisation

`USE_I18N = True`, `LANGUAGES = en-us, pt-br`, `LOCALE_PATHS = parsifal/locale`
(directory absent). Most strings in `reviews` views are not wrapped in
`gettext`; `invites`, `accounts`, `authentication` and templates partially
are. Effective UI language is English.

## Where the fork plugs in

The fork does not change this architecture for the web UI. It adds, beside
it, a **service layer** (plain Python functions encapsulating the rules now
spread across views), a **JSON API** exposing that layer, and **thin CLI/MCP
clients**. Existing views can progressively delegate to the service layer.
Details: [11-system-design.md](11-system-design.md).
