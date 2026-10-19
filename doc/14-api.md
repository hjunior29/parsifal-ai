# 14 — JSON API v1

Implemented in phase 3 with [django-ninja](https://django-ninja.dev/) on top of
the service layer ([11-system-design.md](11-system-design.md) §3). Everything
a member can do in the web UI for a review is available here; the CLI and the
MCP server (phases 4–5) are thin clients of this API.

- Base URL: `/api/v1/`
- Interactive docs (Swagger UI): `/api/v1/docs` · OpenAPI document: `/api/v1/openapi.json`
- Code: `parsifal/api/` (`api.py`, `auth.py`, `errors.py`, `deps.py`,
  `v1/routers/*.py`, `v1/schemas/*.py`), tests in `parsifal/api/tests/`.

## Authentication

| Method | How | Notes |
|--------|-----|-------|
| Personal API token | `Authorization: Bearer pfl_…` | Created in **Settings → API tokens** (`/settings/tokens/`), via `POST /api/v1/tokens`, or `manage.py create_api_token --user <name>`. Stored hashed; shown once. Revoke from the same page or `POST /api/v1/tokens/{id}/revoke`; once revoked it can be deleted (`DELETE /api/v1/tokens/{id}`, 409 while active). |
| Browser session | Django session cookie (+ CSRF token for unsafe methods) | Lets the web UI call the API. |

Requests act **as the token's user**: the author/co-author rules of each
review apply unchanged. Non-members get `404` for a review (existence is not
leaked); owner-only operations return `403` for co-authors. Administrators
(`is_superuser`) additionally list every review and manage users.

## Conventions

- JSON in and out, snake_case, integer ids, ISO-8601 timestamps.
- `GET` collections of articles and reviews are paginated: `?limit=&offset=` →
  `{"count": n, "items": [...]}` (default 100, max 1000). Other collections
  are small and returned as plain arrays.
- `PATCH` = partial update (only the fields sent); `PUT` = replace one value.
- Successful `DELETE` → `204`. Creation → `201`.
- Errors: `{"detail": "...", "code": "...", "field": "..."}` with
  `404 not_found` (also for a child id that belongs to another review),
  `403 permission_denied`, `409 conflict`, `422 validation_error` (domain
  rules) — request-shape errors from the schema layer return Ninja's standard
  `422 {"detail": [...]}`.
- Every operation has a stable `operationId` (e.g. `articles_set_status`);
  the CLI commands and MCP tools are named after them.

## Resources

Paths below are relative to `/api/v1`. `{rid}` = review id.

### Account

| Method & path | operationId | Purpose |
|---------------|-------------|---------|
| `GET /me` · `PATCH /me {first_name?, last_name?, email?}` | `me` · `me_update` | Current user and number of active tokens; change your own profile fields |
| `GET /tokens` · `POST /tokens {name}` · `POST /tokens/{id}/revoke` · `DELETE /tokens/{id}` | `tokens_list` · `tokens_create` · `tokens_revoke` · `tokens_delete` | Manage own tokens (`POST` returns `key` once; delete only after revoking) |
| `GET /users` · `POST /users {username,email,password?,first_name?,last_name?}` | `users_*` | Administrators only |
| `GET /sources/defaults` | `sources_defaults` | The default digital libraries |

### Reviews and membership

| Method & path | operationId |
|---------------|-------------|
| `GET /reviews?author=&name=&q=&limit=&offset=` | `reviews_list` |
| `POST /reviews {title, description?}` | `reviews_create` |
| `GET /reviews/{rid}` · `PATCH /reviews/{rid}` (title, description, objective, population, intervention, comparison, outcome, context, quality_assessment_cutoff_score) · `DELETE` (owner) | `reviews_get` · `reviews_update` · `reviews_delete` |
| `GET /reviews/{rid}/overview` | `reviews_overview` — counts per section and per article status; the first call an agent should make |
| `PUT /reviews/{rid}/name {name}` (owner) | `reviews_rename` |
| `GET /reviews/{rid}/members` | `members_list` (author and co-authors) |
| `GET /reviews/{rid}/agents` · `POST {name}` (owner) · `POST /agents/{id}/token` (owner) · `DELETE /agents/{id}` (owner) | `agents_list` · `agents_create` · `agents_new_token` · `agents_delete` |

An **agent** is an AI co-author with an account of its own, created for one review by its main author; there is no way to add an existing account. `POST /agents` answers with the agent's token, shown once. `POST /agents/{id}/token` revokes its tokens and issues a new one. **Deleting an agent is permanent: it deletes the account, its API tokens and everything recorded under it (screening decisions, quality assessments, extracted data). Studies it imported and classifications it made stay in the review, without an author.** Agents cannot create or delete agents, rename or delete the review.

### Protocol (planning)

| Method & path | operationId |
|---------------|-------------|
| `GET/POST /reviews/{rid}/questions` · `PATCH/DELETE /questions/{id}` · `PUT /questions/order {ids}` | `questions_*` |
| `GET/POST /reviews/{rid}/keywords` (`description`, `related_to` P/I/C/O, `synonyms[]`) · `PATCH/DELETE /keywords/{id}` · `POST /keywords/import-picoc` | `keywords_*` |
| `GET/PUT /reviews/{rid}/search-string` · `POST /search-string/generate` | `search_string_*` |
| `GET/POST /reviews/{rid}/sources` (`{source_id}` default library or `{name,url}` custom) · `PATCH/DELETE /sources/{id}` | `review_sources_*` |
| `GET /reviews/{rid}/sources/search-strings` · `PUT/DELETE /sources/{id}/search-string` · `POST /sources/{id}/search-string/copy-generic` | `source_search_string*` |
| `GET/POST /reviews/{rid}/criteria` (`criteria_type` I/E) · `PATCH/DELETE /criteria/{id}` | `criteria_*` |

### Quality assessment

| Method & path | operationId |
|---------------|-------------|
| `GET/POST /reviews/{rid}/quality/questions` · `PATCH/DELETE /{id}` · `PUT /order` | `quality_questions_*` |
| `GET/POST /reviews/{rid}/quality/answers` (`description`, `weight`) · `POST /answers/suggested` · `PATCH/DELETE /{id}` | `quality_answers_*` |
| `GET /reviews/{rid}/quality/max-score` · `PUT /quality/cutoff {cutoff}` · `GET /quality/summary` | `quality_max_score` · `quality_set_cutoff` · `quality_summary` |
| `GET /reviews/{rid}/articles/{aid}/quality` · `PUT {question_id, answer_id}` | `article_quality_get` · `article_quality_assess` (records the acting user) |

### Data extraction

| Method & path | operationId |
|---------------|-------------|
| `GET/POST /reviews/{rid}/extraction/fields` (`field_type` B/S/F/I/D/O/M, `lookup_values[]`) · `PATCH/DELETE /{id}` · `PUT /order` | `extraction_fields_*` |
| `GET /reviews/{rid}/articles/{aid}/extraction` · `PUT {field_id, value | values[]}` · `PUT /extraction/done {done}` | `article_extraction_*` |

Values: booleans `"True"/"False"`, floats accept `,`, dates `MM/DD/YYYY`
(returned as `YYYY-MM-DD`), select-one takes a lookup id in `value`,
select-many takes the full list of lookup ids in `values` (set semantics).

### Articles (studies)

| Method & path | operationId |
|---------------|-------------|
| `GET /reviews/{rid}/articles?source_id=&status=U|A|R|D&q=&finished_data_extraction=&limit=&offset=` | `articles_list` |
| `POST /reviews/{rid}/articles {source_id, …fields}` | `articles_create` |
| `GET/PATCH/DELETE /reviews/{rid}/articles/{aid}` | `articles_get` · `articles_update` · `articles_delete` |
| `POST /reviews/{rid}/articles/status {ids[], status, selection_criteria_id?, comments?}` | `articles_set_status` |
| `POST /reviews/{rid}/articles/import {source_id, bibtex}` · `POST /articles/import/file` (multipart `source_id`, `file`) | `articles_import` · `articles_import_file` → `{imported, failed, warnings[], article_ids[]}` |
| `GET /reviews/{rid}/articles/duplicates` · `POST /duplicates/resolve {ids?}` | `articles_duplicates` · `articles_resolve_duplicates` |
| `POST /reviews/{rid}/articles/delete {ids}` · `POST /articles/clear {source_id, status?}` | `articles_delete_batch` · `articles_clear` (bulk delete; `clear` empties one source, e.g. after importing the wrong export) |

### Classification, search documentation, test set, checklist (optional for any review; phase 7)

| Method & path | operationId |
|---------------|-------------|
| `GET /facets/templates` | `facet_templates` — research_type, contribution_type, research_method, venue_type, study_focus |
| `GET/POST /reviews/{rid}/facets` (`{template}` or `{name, kind, multiple, categories[]}`) · `PATCH/DELETE /facets/{id}` · `PUT /facets/order` | `facets_*` |
| `POST /reviews/{rid}/facets/{fid}/categories` · `PATCH/DELETE /categories/{id}` · `PUT /categories/order` | `categories_*` |
| `GET /reviews/{rid}/articles/{aid}/classification` · `PUT {facet_id, category_ids[], notes}` | `article_classification_*` (set semantics; single-choice facets accept one id) |
| `GET /reviews/{rid}/analytics/facets/{fid}/frequencies` · `GET /analytics/facet-matrix?rows=&columns=` | `analytics_facet_frequencies` · `analytics_facet_matrix` (bubble-plot cells) |
| `GET/POST /reviews/{rid}/test-set` · `PATCH/DELETE /test-set/{id}` · `POST /test-set/match` | `test_set_*` — known papers, matched by DOI or normalised title; `recall` = found/total |
| `GET /reviews/{rid}/checklist` · `PUT /checklist/{key} {applied, notes}` | `checklist_*` — Petersen et al. (2015) Table 8 actions |
| `PATCH /reviews/{rid}/sources/{sid}/search {search_type, searched_at, years_from, years_to, result_count}` | `source_search_update` — search documentation (K 6.1.4) |

`ReviewOut`/`PATCH` also carry `review_type`, `selection_procedure`,
`synthesis_strategy`, `validity_threats`; `ArticleOut` carries `found_via_id`.
The DOCX report accepts the extra sections `classification_scheme`,
`selection_procedure`, `synthesis_strategy`, `validity_threats`, `test_set`,
`search_documentation`, `classification_results`, `process_checklist`, and its
`quality_assessment` / `data_extraction` / `data_analysis` sections now have
content.

### Multi-reviewer decisions (phase 8)

| Method & path | operationId |
|---------------|-------------|
| `GET /reviews/{rid}/decisions?stage=&user_id=&article_id=&status=` · `POST {ids[], status, stage?, selection_criteria_id?, comments?}` | `decisions_list` · `decisions_record` — records **the caller's** decision; `Article.status` is untouched |
| `GET /reviews/{rid}/articles/{aid}/decisions` · `DELETE /articles/{aid}/decisions/mine?stage=` | `article_decisions` · `decisions_remove_mine` |
| `GET /reviews/{rid}/decisions/summary` | `decisions_summary` |
| `GET /reviews/{rid}/decisions/agreement?stage=&user_a_id=&user_b_id=` | `decisions_agreement` — Cohen's kappa, percent agreement, Landis & Koch label |
| `GET /reviews/{rid}/decisions/disagreements?stage=` | `decisions_disagreements` |
| `POST /reviews/{rid}/decisions/consolidate {stage, rule: unanimous | any_include | majority, ids?}` | `decisions_consolidate` — sets `Article.status` where the rule decides |

Recommended flow for an agent: `decisions_record` its screening decisions
with the criterion as reason; the human reviewer records theirs; both check
`decisions_agreement` / `decisions_disagreements`; the human runs
`decisions_consolidate` (or `articles_set_status` for individual overrides).

### Exclude with AI (Jev) — phase 1 of study selection

| Method & path | operationId |
|---------------|-------------|
| `GET /integrations/jev` · `PUT {api_key?, model?}` · `POST /integrations/jev/test` · `DELETE` | `jev_integration_get` · `jev_integration_set` · `jev_integration_test` · `jev_integration_delete` — the caller's own key (Settings → Integrations); never returned, only `masked_key`. A blank value keeps the saved one. `test` answers 422 if Jev rejects the key, 502 if Jev fails |
| `GET /reviews/{rid}/ai-screening?reviewer_id=` | `ai_screening_setup` — review context defaults, exclusion criteria as `E1…` + `none`, task, rules, threshold range, Jev's models for your key (asked now), who you may screen as, studies per scope for that reviewer |
| `POST /reviews/{rid}/ai-screening/runs {reviewer_id, model?, title?, objective?, research_questions?, population?, intervention?, comparison?, outcome?, context?, guidance?, threshold?, source_id?}` | `ai_screening_start` (201) — decisions recorded as `reviewer_id` (only the main author may name another member); `model` defaults to yours; context fields left out take the review's values |
| `POST /reviews/{rid}/ai-screening/runs/{id}/step {size?}` | `ai_screening_step` — screens the next 1–50 studies (default 8) with the caller's key; returns `{run, results[]}` |
| `POST /reviews/{rid}/ai-screening/runs/{id}/cancel` | `ai_screening_cancel` |
| `GET /reviews/{rid}/ai-screening/runs` · `GET /runs/{id}` · `GET /runs/{id}/results?outcome=` (paginated) | `ai_screening_runs_list` · `ai_screening_runs_get` (with the parameters snapshot) · `ai_screening_results` (probabilities, chosen criterion, errors) |

A run does nothing until `step` is called; call it until `run.status` is no
longer `running` (the web page does the same in the browser; the CLI command
`ai-screening run` and the MCP tool `parsifal_ai_screening_run` loop for
you). A run sends the unclassified studies plus those the reviewer rejected
in an earlier run, and records the reviewer's decision for each: rejected with
a criterion when `p_exclude = 1 − p(none) ≥ threshold` (the study is rejected
too), otherwise unclassified (the study stays, or goes back to, unclassified).

### Library (personal bibliography, independent from reviews)

Everything under `/library/` is scoped to the authenticated user; another
user's folder or document answers `404`.

| Method & path | operationId |
|---------------|-------------|
| `GET/POST /library/folders {name}` · `PATCH /library/folders/{id} {name}` · `DELETE /library/folders/{id}` (documents stay) | `folders_list` · `folders_create` · `folders_rename` · `folders_delete` |
| `POST /library/folders/{id}/documents {ids}` · `POST …/documents/remove {ids}` · `POST …/documents/move {ids, to_folder_id}` | `folders_add_documents` · `folders_remove_documents` · `folders_move_documents` |
| `GET /library/documents?folder_id=&q=&order=&limit=&offset=` (`order`: title, author, year, created_at, `-` to reverse) | `documents_list` |
| `POST /library/documents {BibTeX fields}` · `GET/PATCH/DELETE /library/documents/{id}` · `POST /library/documents/delete {ids}` | `documents_create` · `documents_get` · `documents_update` · `documents_delete` · `documents_delete_batch` |
| `POST /library/import {bibtex, folder_id?}` · `POST /library/import/file` (multipart `file`, `folder_id?`) | `library_import` · `library_import_file` |

### Analytics and exports

| Method & path | operationId |
|---------------|-------------|
| `GET /reviews/{rid}/analytics/selection-by-source` · `GET /analytics/final-by-year` | `analytics_*` |
| `GET /reviews/{rid}/export/articles.{csv|xlsx|json}` · `GET /export/extraction.{csv|xlsx|json}` | `export_articles` · `export_extraction` |
| `GET /reviews/{rid}/export/report.docx?sections=name,picoc,…` | `export_report` (section keys in [07-import-export.md](07-import-export.md)) |

## Example session (curl)

```bash
export PARSIFAL_URL=http://localhost:8000/api/v1
export PARSIFAL_TOKEN=pfl_...
H="Authorization: Bearer $PARSIFAL_TOKEN"

curl -s -H "$H" $PARSIFAL_URL/me
RID=$(curl -s -H "$H" -H 'Content-Type: application/json' \
  -d '{"title":"LLM-assisted SLRs"}' $PARSIFAL_URL/reviews | jq .id)
curl -s -H "$H" -H 'Content-Type: application/json' -X PATCH \
  -d '{"objective":"...","population":"researchers","intervention":"LLM tools"}' $PARSIFAL_URL/reviews/$RID
curl -s -H "$H" -X POST $PARSIFAL_URL/reviews/$RID/keywords/import-picoc
curl -s -H "$H" -X POST $PARSIFAL_URL/reviews/$RID/search-string/generate
curl -s -H "$H" -H 'Content-Type: application/json' \
  -d "{\"source_id\": 7, \"bibtex\": $(jq -Rs . < scopus.bib)}" $PARSIFAL_URL/reviews/$RID/articles/import
curl -s -H "$H" "$PARSIFAL_URL/reviews/$RID/articles?status=U&limit=50"
curl -s -H "$H" -H 'Content-Type: application/json' \
  -d '{"ids":[1,2],"status":"A","selection_criteria_id":3}' $PARSIFAL_URL/reviews/$RID/articles/status
curl -s -H "$H" $PARSIFAL_URL/reviews/$RID/overview
curl -s -H "$H" -o report.docx $PARSIFAL_URL/reviews/$RID/export/report.docx
```

The complete end-to-end scenario is encoded in
`parsifal/api/tests/test_e2e_full_review.py`.

## Bootstrap commands

| Command | Purpose |
|---------|---------|
| `manage.py init --username <name> [--email …] [--password …] [--token NAME]` | Migrate, load default sources, create the administrator (random password printed if omitted), optionally print an API token; warns if `SECRET_KEY` is insecure. Safe to re-run. |
| `manage.py create_api_token --user <username> [--name CLI]` | Print a new token for a user. |
| `manage.py load_default_sources` | Idempotent load of the 7 default digital libraries. |

## Not in v1

Review invites by e-mail and adding existing accounts as co-authors (agents are
created with `agents_create`).
