# 09 — Testing

## Current state

- Test runner: Django's built-in runner (`manage.py test --settings=parsifal.settings.tests`).
- **75 tests**, all passing. Verified on **2026-10-15** against **SQLite** with
  Python 3.9.6 and Django 4.2.28 (`Ran 75 tests in 1.167s — OK`), after
  applying all 87 migrations on an empty SQLite database. No Postgres-specific
  code exists (no `contrib.postgres`, `ArrayField`, `JSONField` or raw SQL).
- Coverage config: `setup.cfg` `[coverage:run]` with `branch = true`, source
  `parsifal`, omitting `*/migrations/*` and `*/tests/*`.
- Fixtures: `parsifal/apps/reviews/fixtures/source_initial_data.json` (7
  default digital libraries) — loaded explicitly by one test.

### Where the tests are

| App | Test files | Lines | What is covered |
|-----|------------|-------|-----------------|
| `invites` | `test_models.py`, `test_invite_detail_view.py`, `test_invite_delete_view.py`, `test_manage_access_view.py`, `factories.py` | 351 | Invite accept/reject, access control, views. The best-tested app. |
| `authentication` | `test_sign_up_view.py`, `test_sign_up_form.py`, `test_validators.py`, `test_user_model.py`, `factories.py` | 229 | Sign-up flow, username/e-mail validators, `UserFactory`/`SuperUserFactory`. |
| `accounts` | `test_update_profile_view.py`, `test_update_emails_view.py`, `test_picture_view.py`, `test_settings_redirect_view.py` | 164 | Settings pages. |
| `reviews` | `test_new_review_view.py`, `test_reviews_view.py`, `factories.py` | ~180 | Review creation, slug uniqueness, review list page. |
| `reviews.settings` | `test_delete_review_view.py` | 65 | Delete review, main-author guard. |
| `reviews.conducting` | `test_views_import_bibtex.py` | 25 | Only asserts the fixture loads — **BibTeX import itself is untested**. |
| `reviews.reporting` | `test_views_export.py` | 27 | Export page renders. |
| `blog` | `test_views.py`, `factories.py` | 67 | List/detail pages. |
| `core` | `test_views_home.py` | 26 | Home page for anonymous/authenticated users. |
| `library`, `activities`, `help`, `reviews.planning` | — | 0 | **No tests.** |

### Conventions used by the existing tests

- `django.test.TestCase` with `setUpTestData` for shared fixtures.
- `factory_boy` `DjangoModelFactory` classes in `tests/factories.py` of each
  app (`UserFactory` creates users through `create_user`, `ReviewFactory`
  supports `co_authors` and `sources` post-generation hooks,
  `SourceFactory`/`DefaultSourceFactory`).
- `self.client.force_login(user)` then assert status codes, redirects
  (`parsifal.utils.test.login_redirect_url` builds `/login/?next=...`),
  `assertContains` on rendered HTML, and model side effects.
- `subTest` blocks to group related assertions.

## Gaps that matter for the fork

1. The whole **planning** and **conducting** AJAX surface (~70 endpoints,
   see [06-http-endpoints.md](06-http-endpoints.md)) has no tests. Since the
   API/CLI/MCP layer will re-implement these behaviours through a service
   layer, the service layer tests become the primary safety net.
2. **Business rules** are untested: final-selection cut-off logic
   (`Review.get_final_selection_articles`), duplicate detection
   (`Review.get_duplicate_articles`), search-string generation, QA score
   aggregation, `DataExtraction.set_value/get_value` coercions.
3. **Import/export** paths (`bibtex_to_article_object`, XLS, DOCX) are
   untested.
4. **Authorization** of action endpoints that take `review-id` plus other ids
   is untested (see IDOR notes in [13-known-issues.md](13-known-issues.md)).

## Testing policy for new work

Everything added by the fork must ship with tests, following the existing
style unless noted:

| Component | Test type | Notes |
|-----------|-----------|-------|
| Service layer (`parsifal/apps/*/services.py`) | Unit tests with factories, no HTTP | Cover every rule listed in the gaps above as the service functions are introduced. |
| HTTP API (`parsifal/api/`) | `django.test.TestCase` + `Client` against `/api/v1/...` with token auth | One test module per router; assert status, JSON shape, permission denials (403/404), and DB side effects. Use the OpenAPI schema test to catch accidental contract changes. |
| CLI | `click`/`typer` `CliRunner` tests with a mocked HTTP client, plus a small number of end-to-end tests against `LiveServerTestCase` | Thin client: test argument parsing, output formatting (JSON/table), exit codes. |
| MCP server | Tool-schema snapshot test + in-process tool invocation tests against a mocked API client | Ensure 1:1 parity with CLI commands via a parity test that diffs the two command inventories. |
| Migrations | `makemigrations --check` (already in tox) + a test that migrates an empty SQLite DB | Keep `tox -e migrations`. |
| Data import/export | Golden-file tests with small `.bib` samples; assert XLS/DOCX contents by reading them back | Place samples under `parsifal/apps/reviews/tests/data/`. |

Target: the tox `py310` env is the single entry point (`coverage run
manage.py test`), with SQLite as the default `DATABASE_URL` so CI no longer
needs Postgres. Coverage should be reported per PR; new modules should land at
≥ 90 % line coverage.

## Running the suite

```bash
# one-off
DATABASE_URL=sqlite:////tmp/parsifal-test.sqlite3 SECRET_KEY=test \
  .venv/bin/python manage.py test --settings=parsifal.settings.tests

# everything (tests + flake8 + isort + migrations check)
.venv/bin/tox
```

Django creates a separate test database, so the `DATABASE_URL` path is only
used to pick the engine. Note that the `tests.py` settings module does not set
`DATABASE_URL`; without the environment variable the Postgres default from
`base.py` applies — the fork changes that default to SQLite (ADR-001).
