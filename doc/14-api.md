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
| `GET /me` · `PATCH /me {first_name?, last_name?, email?, study_columns?}` | `me` · `me_update` | Current user, number of active tokens and `study_columns` (the columns of the study list on Study Selection, in order — the web's Columns window); change your own profile fields |
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
| `POST /reviews/{rid}/selection/reset {reviewer_ids?}` (owner) | `reviews_selection_reset` — back to the start of study selection: every study but duplicates becomes unclassified without a criterion, the decisions of `reviewer_ids` are deleted (every stage), a run in progress is discarded; the AI run log, stars, PDFs, quality and extraction data are kept; returns `{unclassified, decisions_deleted, runs_discarded}` |
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
| `GET /reviews/{rid}/articles/{aid}/quality` · `PUT {question_id, answer_id}` (no `answer_id`: clear the answer) | `article_quality_get` · `article_quality_assess` (records the acting user) |
| `GET /reviews/{rid}/quality/studies?q=&state=done|pending|above|below&order=title|-title|year|-year&limit=&offset=` | `quality_studies` — the accepted studies as Quality Assessment lists them, each with `score` and `answered` (questions with an answer); `q` searches the title; `above`/`below`: score above the cutoff, or at most it |

### Data extraction

| Method & path | operationId |
|---------------|-------------|
| `GET/POST /reviews/{rid}/extraction/fields` (`field_type` B/S/F/I/D/O/M, `lookup_values[]`) · `PATCH/DELETE /{id}` · `PUT /order` | `extraction_fields_*` |
| `GET /reviews/{rid}/articles/{aid}/extraction` · `PUT {field_id, value | values[]}` · `PUT /extraction/done {done}` | `article_extraction_*` |
| `GET /reviews/{rid}/extraction/studies?q=&done=&limit=&offset=` | `extraction_studies` — the final-selection studies as Data Extraction lists them (by title), each with its quality `score`, `finished_data_extraction` and `filled` (fields with a value); `q` searches the title |

Values: booleans `"True"/"False"`, floats accept `,`, dates `MM/DD/YYYY`
(returned as `YYYY-MM-DD`), select-one takes a lookup id in `value`,
select-many takes the full list of lookup ids in `values` (set semantics).

### Articles (studies)

| Method & path | operationId |
|---------------|-------------|
| `GET /reviews/{rid}/articles?source_id=&status=U|A|R|D&q=&finished_data_extraction=&starred=&order=&limit=&offset=` | `articles_list` — `order` is a column of the study list (`title`, the default, `ai_score`, `star`, `bibtex_key`, `author`, `journal`, `year`, `source`, `doi`, `document_type`, `language`, `publisher`, `criteria`, `created_by`, `created_at`, `updated_by`, `updated_at`, `status`; `-` before it reverses it; studies without the value last, ties by title); `order=ai_score`: the most likely relevant first by the latest AI run (every study carries `ai_score`, 0–1: exclusion 1 − p(exclude), inclusion the deciding p(meets), screen the lower; null when no run answered about it); `q` searches the title, DOI (also pasted as a doi.org link) and BibTeX key; `starred=true` keeps the starred ones |
| `POST /reviews/{rid}/articles {source_id, …fields}` | `articles_create` |
| `GET/PATCH/DELETE /reviews/{rid}/articles/{aid}` | `articles_get` · `articles_update` · `articles_delete` |
| `POST /reviews/{rid}/articles/status {ids[] \| all_matching + match_source_id?, match_status?, match_q?, match_starred?; status, selection_criteria_id?, comments?}` | `articles_set_status` — on `ids`, or with `all_matching` on every study that matches the study list's filters (every study when none is given); both or neither → 422 |
| `POST /reviews/{rid}/articles/import {source_id, bibtex}` · `POST /articles/import/file` (multipart `source_id`, `file`) | `articles_import` · `articles_import_file` → `{imported, failed, warnings[], article_ids[]}` |
| `GET /reviews/{rid}/articles/duplicates` · `POST /duplicates/resolve {ids?}` | `articles_duplicates` · `articles_resolve_duplicates` |
| `POST /reviews/{rid}/articles/delete {ids[] \| all_matching + match_*}` · `POST /articles/clear {source_id, status?}` | `articles_delete_batch` · `articles_clear` (bulk delete; `clear` empties one source, e.g. after importing the wrong export) |
| `PUT /reviews/{rid}/articles/{aid}/star` · `DELETE …/star` | `articles_star` · `articles_unstar` → the article. One star per study in the review, shared by every member (`starred`, `starred_by`, `starred_at` on every article); starring again keeps who starred it first; the status is untouched. One study at a time: there is no bulk star |
| `POST /reviews/{rid}/articles/{aid}/pdf` (multipart `file`) · `GET …/pdf` · `DELETE …/pdf` | `articles_pdf_upload` → `201 {filename, content_type, size, sha256, uploaded_by, uploaded_at}` · `articles_pdf_download` (the file, `Content-Disposition: attachment` with the uploaded name; streamed from the bucket too) · `articles_pdf_delete` → 204 |

The study's full text: one PDF per study, any status, up to `PARSIFAL_PDF_MAX_MB` (50 MB by default); anything
else is a 422 on `file`. Uploading again replaces it; the status and `updated_by` are untouched. Every article
carries `pdf` (that object, or `null`); 404 when downloading or deleting a PDF that does not exist.

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
| `GET /reviews/{rid}/decisions/disagreements?stage=&user_a_id=&user_b_id=` | `decisions_disagreements` — between the two reviewers given (different ones), else among all; still listed after a consolidation (decisions are kept); `article.status` / `article.updated_by` show whether it was settled |
| `POST /reviews/{rid}/decisions/consolidate {stage, rule: unanimous | any_include | majority, ids?, user_ids?}` | `decisions_consolidate` — only the decisions of `user_ids` (at least two) when given; sets `Article.status` (and `updated_by`) where the rule decides → `{resolved, unresolved, changed, resolved_ids, unresolved_ids, changed_ids}`; `changed` are those whose status was different |

Recommended flow for an agent: `decisions_record` its screening decisions
with the criterion as reason; the human reviewer records theirs; both check
`decisions_agreement` / `decisions_disagreements`; the human runs
`decisions_consolidate` (or `articles_set_status` for individual overrides).

### Exclude and include with AI (Jev) — phases 1 and 2 of study selection

| Method & path | operationId |
|---------------|-------------|
| `GET /integrations/library-access` · `PUT {address}` · `DELETE` | `library_access_get` · `library_access_set` · `library_access_delete` — your library proxy (Settings → Library access), e.g. your institution's CAPES access: `{configured, proxy, label, updated_at}`. `address` is the proxy's or that of any page opened through it; only the proxy's address is kept (422 when it is not a web address, or is the CAPES portal itself). Every `ArticleOut` then carries `access_url` (the DOI, else the URL, through the proxy; null without one) |
| `GET /integrations/jev` · `PUT {api_key?, model?}` · `POST /integrations/jev/test {api_key?}` · `DELETE` | `jev_integration_get` · `jev_integration_set` · `jev_integration_test` · `jev_integration_delete` — the caller's own key (Settings → Integrations); never returned, only `masked_key`. A blank value keeps the saved one. `test` lists Jev's models for the saved key, or for `api_key` without saving it (what Settings uses while you type), and answers 422 if Jev rejects the key, 502 if Jev fails |
| `GET /reviews/{rid}/ai-screening?phase=exclusion|inclusion|screen&defaults=` | `ai_screening_setup` — `start`: every setting a run of the action starts from (`from_run_id`, `reviewer_id`, `model`, `context`, `guidance`, `template`, `threshold`, `thresholds`, `source_id`, `statuses`, `criteria_ids`): the review's last run of that action's, or Parsifal's defaults with `defaults=true` (or when there is no run yet); the review's criteria of the action (exclusion: `E1…` + `none`; inclusion: `I1…`, one yes/no question each; screen: both; `question_type` `choice`, `noul` or `choice+noul`), `inclusion_rule` (all/any), `template_default`, `placeholders`, threshold range (0.9, 0.5, 0.99; `inclusion_threshold_min` 0.01), Jev's models for your key, who you may screen as, the unfinished run, studies per scope and status, step sizes |
| `POST /reviews/{rid}/ai-screening/runs {reviewer_id, phase?, model?, title?, objective?, research_questions?, population?, intervention?, comparison?, outcome?, context?, guidance?, template?, threshold?, thresholds?, source_id?, statuses?, criteria_ids?, defaults?}` | `ai_screening_start` (201) — decisions recorded as `reviewer_id` (only the main author may name another member). Whatever is left out takes the setup's `start` (the last run of the action), or Parsifal's defaults with `defaults`; `source_id` 0 means all sources. `criteria_ids`: the criteria sent (`skipped_criteria` in the parameters). `threshold` 0.5–0.99 to reject (exclusion and screen); `thresholds` per inclusion criterion, 0.01–0.99 (`{"I1": 0.9}` or `["I1=0.9"]`; inclusion and screen), combined by the protocol's `inclusion_rule` (kept in the parameters). Screen: rejected when the exclusion threshold is reached, else accepted when the inclusion criteria are met, else unclassified. `phase=retention` is refused (422: Retain with AI was removed) |
| `POST /reviews/{rid}/ai-screening/preview {phase?, model?, <context fields>?, guidance?, template?, source_id?, statuses?, criteria_ids?, defaults?, article_id?}` | `ai_screening_preview` — the body a run with these settings would send to Jev (`model`, `state`, `questions`) about `article_id` or the first study in scope with a title or abstract; what is left out as in the start operation; nothing is sent |
| `POST /reviews/{rid}/ai-screening/runs/{id}/step {size?}` | `ai_screening_step` — screens the next 1–64 studies (default 64), up to 32 at a time and spaced under Jev's rate limit (`JEV_REQUESTS_PER_MINUTE`), with the caller's key; returns `{run, results[]}` |
| `GET /reviews/{rid}/ai-screening/runs` · `GET /runs/{id}` · `GET /runs/{id}/results?outcome=` (paginated) | `ai_screening_runs_list` · `ai_screening_runs_get` (with the parameters snapshot) · `ai_screening_results` (`status`: the status the run gave the study, R, A or U, and `kept_status` when the study kept another; probabilities, `p_exclude`, `p_include`, criterion, errors; `outcome` excluded, passed, included, undecided, error, pending). Every run carries `standing` (its decisions that are still the reviewer's; null for runs made before Parsifal kept what came before a run), `undoable` and `undo_blocked` (why you cannot undo it now) |
| `POST /reviews/{rid}/ai-screening/impact {phase?, reviewer_id?, statuses?, source_id?, run_id?, defaults?}` | `ai_screening_impact` — what a run would rewrite before starting it: `studies` it sends, `decisions` of the reviewer it replaces, `classified` (studies the reviewer classified with a status the run may change), `confirm` (either is not zero), `message`; what is left out takes the last run's settings, or with `run_id` that run's. The CLI asks it before `start`, `run` and `rerun` on a terminal |
| `POST /reviews/{rid}/ai-screening/runs/{id}/rerun {reviewer_id?, model?, threshold?, thresholds?, statuses?, source_id?, criteria_ids?}` | `ai_screening_rerun` (201) — a new run with the settings of run `id` (action, reviewer, model, context, guidance, template, thresholds, criteria, source, statuses), changing those given; the criteria are the review's current ones (those the run left out stay out; an inclusion criterion keeps its threshold, matched by id; in inclusion `threshold` alone replaces them all). Retention runs cannot be run again. Step it as any run |
| `GET /reviews/{rid}/ai-screening/runs/{id}/undo` · `POST …/undo` | `ai_screening_undo_preview` · `ai_screening_undo` (destructive) — `{screened, statuses_restored, back_to {status: n}, statuses_kept, decisions_restored, decisions_removed, decisions_kept, message}`. Undo takes back what still stands of the run — studies whose status it changed and nobody changed since go back to their status, criterion and last editor from before; the reviewer's decisions still the run's go back to the ones it replaced, or are removed — then deletes the run. Only the review's latest run can be undone; the run before it becomes the latest. 403 for another reviewer's run unless main author, 409 while a run is being screened, 422 for a run that is not the latest and for runs made before Parsifal kept what came before a run |

A run does nothing until `step` is called; call it until `run.status` is no
longer `running`. A run cannot be cancelled: if Jev refuses the key or is
unavailable, the step returns with `run.error` set and the remaining studies
kept, and stepping it again later continues it (with the parameters it started
with); starting a new run discards an unfinished one (the web page does the same in the browser; the CLI command
`ai-screening run` and the MCP tool `parsifal_ai_screening_run` loop for
you). A run sends the studies with the chosen statuses and records the
reviewer's decision for each: rejected with a criterion when
`p_exclude = 1 − p(none) ≥ threshold`, otherwise unclassified. The study's
status follows only when it was unclassified (rejected, or stays unclassified)
or rejected by this same reviewer (new criterion, or back to unclassified);
accepted studies, duplicates and studies rejected by someone else keep theirs,
so two reviewers can screen the same studies and be compared.

What is sent about each study is the run's request template
(`services/screening_requests.py`): a JSON object with `state` (what Jev reads)
and `question` (what it is asked), where `{{review}}`, `{{review.title}}`…,
`{{guidance}}`, `{{study}}`, `{{study.title}}`, `{{study.keywords}}`,
`{{study.abstract}}`, `{{key}}` and `{{criterion}}` are filled in by Parsifal and
everything else is the reviewer's to word. The question keeps its `type`, and
its `criteria` keep the keys Parsifal reads the answers by (exclusion: one
`{{key}}` entry, repeated per criterion, and `none`; inclusion: `true` and
`false`). Each question is asked once (exclusion: `exclusion`; inclusion:
`inclusion_I1`…) and its answer read directly. Runs store it in
`parameters.template`.

An inclusion run asks one yes/no question (Jev's `noul`) per inclusion
criterion and keeps the probability of yes, `p(meets)`, per criterion in
`probabilities`. Each criterion has its own threshold (`thresholds`, stored in
`parameters.thresholds`). It records "accepted" when every `p(meets)` reaches
its threshold, else "unclassified" (outcome `undecided`); `p_include` is the
`p(meets)` of the deciding criterion, the closest to (or furthest below) its
threshold; it never rejects (`p_exclude` stays
null). The status rule mirrors exclusion: it changes unclassified studies and
those this reviewer accepted (accepted, or back to unclassified); rejected
studies, duplicates and studies accepted by someone else keep theirs.

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
| `GET /reviews/{rid}/analytics/selection-summary` · `GET /analytics/criteria-usage` · `GET /analytics/studies-by-year` | `analytics_selection_summary` (total, duplicated, unique, accepted, rejected, unclassified, final, the shares — duplicates of the imported, the others of the not duplicated —, per source) · `analytics_criteria_usage` (exclusion criteria by the rejected studies with them and inclusion criteria by the accepted ones, most used first; studies without a criterion) · `analytics_studies_by_year` (not duplicated, per year and status) — what the Data Analysis page shows below its first charts |
| `GET /reviews/{rid}/analytics/quality` · `GET /analytics/extraction` | `analytics_quality` (over the accepted studies: assessed — every question answered —, partly, not yet; with a cutoff, above it and at most it; the fully assessed per score; per question, the studies with each answer and none) · `analytics_extraction` (final selection: studies, done, and per single choice, multiple choice or true/false field the studies per option, most chosen first, answered and unanswered; text, number and date fields left out) — the Quality Assessment and Data Extraction sections of Data Analysis |
| `GET /reviews/{rid}/analytics/prisma` · `PUT /analytics/prisma {not_retrieved_criteria_id}` | `analytics_prisma` (the PRISMA 2020 flow diagram in numbers: records per source — snowballing, manual and other search sessions go to `other_methods` —, duplicates, screened, excluded without a full-text decision with `excluded_by_people` / `excluded_by_automation` — only AI agents rejected them at the screening —, `sought`, `not_retrieved`, `assessed`, `excluded_reports` per criterion, `included` — accepted at the full text —, `awaiting_screening`, `awaiting_full_text`) · `analytics_prisma_settings` (the exclusion criterion meaning "full text not retrieved"; null or 0: none) |
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
