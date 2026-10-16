# 06 — HTTP Endpoint Inventory

This is the complete list of routes exposed by the application, derived from
`parsifal/urls.py` and each app's `urls.py`. It serves two purposes:

1. understand what the web UI can do today;
2. define the **functional contract that the fork's JSON API, CLI and MCP
   tools must cover end-to-end** (see [11-system-design.md](11-system-design.md)).

Conventions used below:

- **Guard** — `L` = `login_required`; `A` = `author_required` (author or
  co-author of the review); `M` = `main_author_required` (author only);
  `–` = none. Guards resolve the review from URL kwargs or from the
  `review-id` parameter (see [02-architecture.md](02-architecture.md)).
- **Method** — the method the view actually reads; "GET*" marks a
  **state-changing GET** (no CSRF protection, inherited design flaw).
- Parameter names are the literal form field names used by the JavaScript.
- "frag" = HTML fragment; "text" = plain-text body; 400 = `HttpResponseBadRequest`
  (usually empty) on any exception.

## 1. Authentication and accounts

| Path | Method | Guard | Purpose |
|------|--------|-------|---------|
| `/login/`, `/logout/`, `/password_change/`, `/password_change/done/`, `/password_reset/`, `/password_reset/done/`, `/reset/<uidb64>/<token>/`, `/reset/done/` | GET/POST | – | `django.contrib.auth.urls` with templates in `templates/registration/`. Login accepts username **or** e-mail (custom backend). |
| `/login/success/` | GET | L | Redirect to `/<username>/`. |
| `/signup/` | GET/POST | – | `SignUpView`; fields `username`, `email`, `password1`, `password2`, hidden `invite` (uuid). Since phase 1: 403 unless `PARSIFAL_ALLOW_SIGNUP` or a pending invite code is given; reCAPTCHA removed. The cover page posts `password2 = password1`. |
| `/signin/` | GET | – | Redirect to login. |
| `/settings/` → `/settings/profile/` | GET/POST | L | `ProfileForm`: `first_name`, `last_name`, `public_email`, `location`, `url`, `institution`. |
| `/settings/emails/` | GET/POST | L | `UserEmailForm.email` (unique, case-insensitive). |
| `/settings/picture/` | GET | L | Picture page. |
| `/settings/upload_picture/` | POST multipart | L | `picture` file → saves `<MEDIA_ROOT>/profile_pictures/<username>_tmp.jpg`, resizes to 560 px wide. |
| `/settings/save_uploaded_picture/` | POST | L | `x`, `y`, `w`, `h` → crops to 200×200 `<username>.jpg`; returns image URL text. |
| `/admin/` | | staff | Django admin. Registered: `reviews.Review`, `invites.Invite`, `core.Media`, `blog.Entry`, `help.Category`/`help.Article`. No admin for `library`, `accounts`/`Profile`, `activities`. |

## 2. Public / SaaS pages (removed in phase 1, ADR-003 — kept for reference)

| Path | Method | Guard | Purpose |
|------|--------|-------|---------|
| `/` | GET | – | Cover + sign-up form for anonymous users; home with review list, follow feed and latest blog entry when logged in. |
| `/about/` | GET | – | Static template. |
| `/blog/`, `/blog/<slug>/` | GET | – | Blog entries. |
| `/help/`, `/help/search/?q=`, `/help/<slug>/` | GET | – | Help articles. |
| `/activity/follow/`, `/activity/unfollow/` | GET* | L | `user-id`. |
| `/activity/update_followers_count/` | GET | – | `user-id` → count text. |
| `/<username>/following/`, `/<username>/followers/` | GET | – | Lists. |
| `/sitemap.xml`, `/robots.txt` | GET | – | |

## 2b. Added by the fork

| Path | Guard | Purpose |
|------|-------|---------|
| `/docs/`, `/docs/<slug>/` | – | In-app documentation of the new features (phase 9). |
| `/settings/tokens/`, `/settings/tokens/<id>/revoke/` | L | API tokens (phase 3). |
| `/api/v1/...` | token or session | JSON API — [14-api.md](14-api.md). |
| `/media/<path>` | – | Uploaded pictures served by Django (phase 6). |

## 3. Reviews — lifecycle and membership

> 2026-10-16 (ADR-008): invites, `transfer`, the Scopus endpoints, picture
> upload/crop and public `/<username>/` pages were removed; `/<username>/`
> now serves only the logged-in user's own list and co-authors are managed at
> `/<username>/<review_name>/settings/access/`.

| Path | Method | Guard | Inputs | Output |
|------|--------|-------|--------|--------|
| `/<username>/` | GET | – | | Review list of that user (author + co-author), pending invites. |
| `/reviews/new/` | GET/POST | L | `title` (≤255, required), `description` (≤500) | Creates review with generated slug; redirect to review page. |
| `/<username>/<review_name>/` | GET/POST | A | `ReviewForm`: `title`, `description` | Review overview page. |
| `/reviews/save_description/` | POST | A | `review-id`, `description` (≤500) | text message / 400 with message if too long. |
| `/<username>/<review_name>/settings/` | GET/POST | M | `name` (slug; collisions suffixed) | Rename URL. |
| `/review_settings/transfer/` | POST | M | `review-id`, `transfer-user` (username) | New author = target; old author becomes co-author. |
| `/<username>/<review_name>/settings/delete/` | POST | M | | Deletes review and its non-default sources (atomic). |
| `/reviews/remove_author/` | POST | M | `review-id`, `user-id` | Remove co-author. |
| `/reviews/leave/` | POST | A | `review-id` | Current user leaves co-authorship. |
| `/<username>/<review_name>/settings/invites/` | GET/POST | M | `invitee` (user id among people you follow) **xor** `invitee_email` | Create `Invite`, send e-mail with `/invites/<code>/` link. |
| `/<username>/<review_name>/settings/invites/<id>/delete/` | POST | M | | Delete pending invite. |
| `/invites/` | GET | L | | Pending invites for current user. |
| `/invites/<id>/accept/`, `/invites/<id>/reject/` | POST | L (invitee) | | Accept → added to `co_authors`. |
| `/invites/<uuid:code>/` | GET | – | | Public invite landing page (masked e-mail). |

## 4. Planning phase

Pages (guard A, GET): `/<u>/<r>/planning/` → redirect, `/planning/protocol/`,
`/planning/quality/`, `/planning/extraction/`.

Action endpoints, all under `/reviews/planning/`, guard **A** unless noted:

| Endpoint | Method | Inputs | Output / side effect |
|----------|--------|--------|----------------------|
| `save_objective/` | POST | `review-id`, `objective` (≤1000) | text; 400 with message if too long |
| `save_picoc/` | POST | `review-id`, `population`, `intervention`, `comparison`, `outcome`, `context` (each truncated to 200) | empty |
| `save_question/` | POST | `review-id`, `question-id` (`None` to create), `description` (≤500) | frag `partial_planning_question.html` |
| `add_or_edit_question/` | POST | `review-id`, `question-id` | frag form |
| `save_question_order/` | POST | `orders` = `"id:order,id:order,…"` | empty (no review scoping) |
| `remove_question/` | POST | `review-id`, `question-id` | empty |
| `import_pico_keywords/` | GET* | `review-id` | Splits each PICO field on `,`, creates `Keyword(related_to=P/I/C/O)` for new terms; frag of new keywords |
| `add_keyword/` | GET (form) / POST (save) | `review-id`; `KeywordForm` (`description`, `related_to`) + synonym formset `synonym-N-description` | JSON `{status: new|ok|validation_error, html}` |
| `edit_keyword/` | GET/POST | `review-id`, `keyword-id` + same forms (inline formset of synonyms) | JSON |
| `remove_keyword/` | GET* | `review-id`, `keyword-id` | empty; deletes synonyms |
| `generate_search_string/` | GET | `review-id` | text `("k" OR "s") AND ("k2" OR …)` grouped by PICO category |
| `save_generic_search_string/` | POST | `review-id`, `search-string` | empty; upserts `SearchSession(source=None)` |
| `suggested_sources/` | GET | `review-id` | frag rows of default sources not yet attached |
| `add_suggested_sources/` | POST | `review-id`, `source-id` (multi) | frag rows |
| `save_source/` | GET* | `review-id`, `source-id` (optional), `name` (≤100), `url` (≤200) | Creates or edits a `Source` and attaches it; frag `<tr>` |
| `remove_source/` | GET* | `review-id`, `source-id` | Detaches; default source → deletes review articles + search string from it; custom → deletes `Source` row |
| `add_criteria/` | GET* | `review-id`, `criteria`, `criteria-type` (`I`/`E`) | frag `<option>` |
| `remove_criteria/` | GET* | `review-id`, `criteria-ids` (csv) | empty |
| `add_quality_assessment_question/` | GET | | frag empty form |
| `edit_quality_assessment_question/` | GET | `review-id` (sent by JS, used only by the guard), `quality-question-id` | frag form (child lookup not scoped to the review) |
| `save_quality_assessment_question/` | POST | `review-id`, `quality-question-id` (`None`/id), `description` | frag |
| `save_quality_assessment_question_order/` | POST | `orders` | empty |
| `remove_quality_assessment_question/` | GET* | `review-id`, `quality-question-id` | empty (child lookup not scoped) |
| `add_quality_assessment_answer/` | GET | | frag empty form |
| `edit_quality_assessment_answer/` | GET | `review-id`, `quality-answer-id` | frag (child lookup not scoped) |
| `save_quality_assessment_answer/` | POST | `review-id`, `quality-answer-id`, `description`, `weight` (float; `,`→`.`; invalid → 0.0) | frag |
| `remove_quality_assessment_answer/` | GET* | `review-id`, `quality-answer-id` | empty (child lookup not scoped) |
| `add_suggested_answer/` | GET* | `review-id` | Creates Yes/Partially/No (1/0.5/0) if none exist; frag rows; else 400 |
| `calculate_max_score/` | GET | `review-id` | text number |
| `save_cutoff_score/` | GET* | `review-id`, `cutoff-score` (float) | text |
| `add_new_data_extraction_field/` | GET | | frag empty form |
| `edit_data_extraction_field/` | GET | `review-id`, `field-id` | frag (child lookup not scoped) |
| `save_data_extraction_field/` | POST | `review-id`, `field-id` (`None`/id), `description`, `field-type` (`B/S/F/I/D/O/M`), `lookup-values` (newline-separated) | frag; type change clears values; lookups synced |
| `save_data_extraction_field_order/` | POST | `orders` | empty |
| `remove_data_extraction_field/` | GET* | `review-id`, `field-id` | empty (child lookup not scoped) |

## 5. Conducting phase

Pages (guard A, GET): `/<u>/<r>/conducting/` → redirect, `/conducting/search/`,
`/conducting/import/`, `/conducting/studies/?source=<id>`,
`/conducting/quality/?order=title|-title|year|-year`,
`/conducting/extraction/?tab=todo|done|all`, `/conducting/analysis/`.
Each page computes `steps_messages` (prerequisites not yet met) and only
renders its tool when `finished_all_steps`.

Action endpoints under `/reviews/conducting/`, guard **A** unless noted:

| Endpoint | Method | Inputs | Output / side effect |
|----------|--------|--------|----------------------|
| `add_source_string/` | POST | `review-id`, `source` (multi ids) | Creates empty `SearchSession` per source; redirect |
| `save_source_string/` | POST | `review-id`, `source-id`, `search_string` | empty |
| `import_base_string/` | POST | `review-id`, `source-id` | Copies generic string into the source session; text |
| `remove_source_string/` | POST | `review-id`, `source-id` | Deletes session; redirect |
| `search_scopus/` | GET | `review-id`, `query`, `count`=25, `start`=0 | JSON from Elsevier; 400 text on invalid query / quota |
| `search_science_direct/` | GET | | always 404 |
| `import/bibtex_file/` | POST multipart | `review-id`, `source-id`, `bibtex` (.bib/.bibtex) | Creates `Article`s; redirect with counts |
| `import/bibtex_raw_content/` | POST | `review-id`, `source-id`, `bibtex_file` (text) | same |
| `new_article/` | GET | `review-id`, `source-id` | frag empty article form |
| `source_articles/` | GET | `review-id`, `source-id` (`None` = all) | frag table of articles |
| `article_details/` | GET | `review-id`, `article-id` | frag details form |
| `save_article_details/` | POST | `review-id`, `article-id` (`None` to create; then `source-id`), `bibtex-key`, `title`, `author`, `journal`, `year`, `pages`, `volume`, `abstract`, `document-type`, `doi`, `url`, `affiliation`, `author_keywords`, `keywords`, `publisher`, `issn`, `language`, `note`, `comments`, `status` (`U/R/A/D`), `selection_criteria` (id or empty) | frag `<tr>`; sets `updated_by` |
| `multiple_articles_action/accept/` · `reject/` · `unclassify/` · `duplicated/` · `remove/` | POST | `review-id`, `article_ids` (`"1|2|3"`) | Bulk status update / delete, scoped to review |
| `find_duplicates/` | GET | `review-id` | frag groups by slugified title |
| `resolve_duplicated/` | POST | `article-id` | status `D` (checks review membership) |
| `resolve_all/` | POST | `review-id` | Marks all but first of each group `D`; csv of ids |
| `export_results/` | POST | `review-id` | `articles.xls` |
| `save_quality_assessment/` | POST | `article-id`, `question-id`, `answer-id` | Upsert assessment; text score (**no review scoping**) |
| `quality_assessment_detailed/` | GET | `review-id` | frag per-article tables (order from session) |
| `quality_assessment_summary/` | GET | `review-id` | frag |
| `save_data_extraction/` | POST | `article-id`, `field-id`, `value` | Upsert + `set_value`; empty; 400 with error text on coercion failure (checks `article.review`) |
| `save_data_extraction_status/` | POST | `article-id`, `action` (`mark_as_done` / other) | toggles `finished_data_extraction` (**no review scoping**) |
| `export_data_extraction/` | POST | `review-id` | `data_extraction.xls` (final selection) |
| `articles_selection_chart/` | GET | `review-id` | text `Source:total:accepted,…` (**no auth at all**) |
| `articles_per_year/` | GET | `review-id` | text `year:count,…` for final selection (**no auth at all**) |

## 6. Reporting phase

| Path | Method | Guard | Inputs | Output |
|------|--------|-------|--------|--------|
| `/<u>/<r>/reporting/` | GET | A | | redirect to export |
| `/<u>/<r>/reporting/export/` | GET | A | | Section checklist page |
| `/reviews/reporting/download_docx/` | GET | A | `review-id`, `export` (multi: section keys listed in [07-import-export.md](07-import-export.md)) | `<name>.docx` |

## 7. Library

All guard **L**, under `/library/`:

| Endpoint | Method | Inputs | Output |
|----------|--------|--------|--------|
| `` (index) | GET | `q` (title contains), `o` (title/author/year ±), `p` (page, 100/page) | page |
| `folders/<slug>/` | GET | same | page scoped to folder (no ownership check) |
| `shared/<slug>/` | GET | same | page scoped to shared folder |
| `new_folder/` | POST | `name` (≤50, unique per user), `user` | JSON `{folder:{id,name,slug}}` / 400 JSON errors |
| `edit_folder/` | POST | `id`, `name`, `delete`=`delete` to remove | redirect |
| `new_shared_folder/` | POST | `name` | JSON |
| `new_document/` | GET / POST | `DocumentForm` (all BibTeX fields) | JSON `{status, html|redirect_to}` |
| `documents/<id>/` | GET / POST | `DocumentForm` | JSON (no ownership check) |
| `list_actions/` | POST | `action` ∈ `move|copy|remove_from_folder|delete_documents`, `document` (multi), `select-all-pages`=`all`, `querystring`, `active-folder-id`, `action-folder-id`, `redirect` | redirect |
| `move/`, `copy/`, `remove_from_folder/`, `delete_documents/` | POST | same as above | redirect |
| `import_bibtex/` | POST multipart | `bibtex`, `add-to-folder-id`, `redirect` | redirect |

## 8. Coverage map for the fork's API (implemented in phase 3 — see [14-api.md](14-api.md))

Every row in sections 3–7 maps to one or more API operations. Rows marked
"no review scoping" or "no auth" must be fixed in the service layer rather than
reproduced. Rows in section 2 are dropped. A first grouping of resources:

| Resource | Operations needed |
|----------|-------------------|
| reviews | list, create, get, update (title, description, objective, PICOC, cutoff, name), delete, transfer, members (list/add/remove) |
| research questions | list, create, update, delete, reorder |
| keywords | list, create (with synonyms), update, delete, import-from-PICOC, generate-search-string |
| search strings | get/set generic; per-source list/set/delete/copy-from-generic |
| sources | list defaults; list/add/create/remove for a review |
| selection criteria | list, create, delete |
| QA questions / answers | list, create, update, delete, reorder; suggested answers; max score |
| extraction fields | list, create, update (with lookups), delete, reorder |
| articles | list (filter by source/status/search), create, get, update, delete; bulk status; import BibTeX; find/resolve duplicates; export |
| quality assessments | get per article; set answer; summary |
| data extraction | get per article; set value (set semantics for select-many); mark done/undone; export |
| analytics | per-source counts; per-year counts |
| reports | generate DOCX with sections |
| library | documents CRUD, folders CRUD, import BibTeX (optional in v1) |
| auth | API tokens for the current user |
