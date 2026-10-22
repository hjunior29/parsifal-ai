# JSON API

Every operation of a review is available at `/api/v1/`. The interactive
reference (Swagger UI) is at [/api/v1/docs](/api/v1/docs) and the OpenAPI
document at `/api/v1/openapi.json`.

## Basics

- Authenticate with `Authorization: Bearer <token>` ([API tokens](/docs/api-tokens/))
  or with your browser session.
- You see the reviews you take part in; a review you are not part of answers
  `404`. Operations reserved to the main author (delete, rename,
  manage members) answer `403` for co-authors.
- JSON in and out; `PATCH` sends only the fields to change; `DELETE` answers
  `204`; creations answer `201`.
- Lists of reviews and articles are paginated: `?limit=&offset=` →
  `{"count": n, "items": [...]}`.
- Errors carry a message and a code: `{"detail": "...", "code": "not_found" |
  "permission_denied" | "conflict" | "validation_error", "field": "..."}`.
- Every operation has a stable `operationId`; the CLI commands and the MCP
  tools are named after them.

## Resource map

| Resource | Paths |
|----------|-------|
| Account | `/me` (GET, PATCH), `/tokens`, `/users` (administrators), `/sources/defaults`, `/integrations/library-access` (GET, PUT, DELETE: your library proxy, e.g. CAPES; studies then carry `access_url` — see [Open studies through CAPES](/docs/library-access/)) |
| Reviews | `/reviews`, `/reviews/{id}`, `/overview`, `/name`, `/members`, `/selection/reset` (back to the start of study selection; main author) |
| Protocol | `/questions`, `/keywords` (+ `/import-picoc`), `/search-string` (+ `/generate`), `/sources` (+ `/search-strings`, `/{id}/search-string`, `/{id}/search`), `/criteria` |
| Quality assessment | `/quality/questions`, `/quality/answers` (+ `/suggested`), `/quality/max-score`, `/quality/cutoff`, `/quality/summary`, `/articles/{id}/quality` |
| Data extraction | `/extraction/fields`, `/articles/{id}/extraction` (+ `/done`) |
| Articles | `/articles` (list, create), `/articles/{id}`, `/articles/status`, `/articles/import`, `/articles/import/file`, `/articles/duplicates` (+ `/resolve`), `/articles/{id}/pdf` (POST multipart `file`, GET, DELETE: the study's PDF; each article carries `pdf` or `null`), `/articles/{id}/star` (PUT, DELETE: the study's star in the review, shared by every member; `?starred=true` on the list) |
| Classification (optional) | `/facets` (+ templates, categories), `/articles/{id}/classification`, `/analytics/facets/{id}/frequencies`, `/analytics/facet-matrix`, `/test-set`, `/checklist` |
| Multiple reviewers | `/decisions`, `/articles/{id}/decisions`, `/decisions/agreement`, `/decisions/disagreements`, `/decisions/consolidate` |
| Exclude, include and screen with AI (Jev) | `/integrations/jev` (+ `/test`; not review-scoped), `/ai-screening?phase=`, `/ai-screening/preview`, `/ai-screening/impact`, `/ai-screening/runs` (+ `/{id}`, `/{id}/step`, `/{id}/results`, `/{id}/rerun`, `/{id}/undo`; `phase` exclusion, inclusion or screen; `/ai-screening?defaults=true` for Parsifal's defaults instead of the last run's settings) — see [Exclude, include and screen with AI](/docs/ai-screening/) |
| Library (personal, not review-scoped) | `/library/folders` (+ `/{id}/documents`, `/remove`, `/move`), `/library/documents` (+ `/delete`), `/library/import` (+ `/file`) |
| Analytics and exports | `/analytics/selection-by-source`, `/analytics/final-by-year`, `/analytics/selection-summary`, `/analytics/criteria-usage`, `/analytics/studies-by-year` (what Data Analysis shows), `/export/articles.{csv,xlsx,json}`, `/export/extraction.{csv,xlsx,json}`, `/export/report.docx` |

All review-scoped paths are prefixed with `/api/v1/reviews/{review_id}`; the library paths are scoped to the
authenticated user instead.

## Example

```bash
H="Authorization: Bearer $PARSIFAL_TOKEN"; U=$PARSIFAL_URL/api/v1
RID=$(curl -s -H "$H" -H 'Content-Type: application/json' \
  -d '{"title":"LLM-assisted SLRs"}' $U/reviews | jq .id)
curl -s -H "$H" -H 'Content-Type: application/json' -X PATCH \
  -d '{"objective":"Map tool support","population":"researchers","intervention":"LLM tools"}' $U/reviews/$RID
curl -s -H "$H" -X POST $U/reviews/$RID/keywords/import-picoc
curl -s -H "$H" -H 'Content-Type: application/json' \
  -d "{\"source_id\": 7, \"bibtex\": $(jq -Rs . < scopus.bib)}" $U/reviews/$RID/articles/import
curl -s -H "$H" "$U/reviews/$RID/articles?status=U&limit=50"
curl -s -H "$H" -H 'Content-Type: application/json' \
  -d '{"ids":[1,2],"status":"A","selection_criteria_id":3}' $U/reviews/$RID/articles/status
curl -s -H "$H" $U/reviews/$RID/overview
curl -s -H "$H" -o report.docx $U/reviews/$RID/export/report.docx
```

`GET /reviews/{id}/overview` is the best first call for any automation: it
returns counts per protocol section and per article status, so the caller can
tell what is missing.
