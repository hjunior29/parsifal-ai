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
| Personal API token | `Authorization: Bearer pfl_…` | Created in **Settings → API tokens** (`/settings/tokens/`), via `POST /api/v1/tokens`, or `manage.py create_api_token --user <name>`. Stored hashed; shown once. Revoke from the same page or `DELETE /api/v1/tokens/{id}`. |
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
| `GET /me` | `me` | Current user and number of active tokens |
| `GET /tokens` · `POST /tokens {name}` · `DELETE /tokens/{id}` | `tokens_*` | Manage own tokens (`POST` returns `key` once) |
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
| `GET /reviews/{rid}/members` · `POST {username | email}` (owner) · `DELETE /members/{user_id}` (owner, or self to leave) | `members_*` |

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
| `manage.py init [--username admin] [--email …] [--password …] [--token NAME]` | Migrate, load default sources, create the administrator (random password printed if omitted), optionally print an API token; warns if `SECRET_KEY` is insecure. Safe to re-run. |
| `manage.py create_api_token --user <username> [--name CLI]` | Print a new token for a user. |
| `manage.py load_default_sources` | Idempotent load of the 7 default digital libraries. |

## Not in v1

Library (documents/folders), review invites by e-mail (use `members_add`),
and the phase 7–8 resources (facets, per-reviewer decisions, agreement).
