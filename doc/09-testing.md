# 09 — Testing

## Current state

- Test runner: Django's built-in runner (`manage.py test --settings=parsifal.settings.tests`).
- Upstream shipped **75 tests**, all passing. Verified on **2026-10-15**
  against **SQLite** with Python 3.9.6 and Django 4.2.28 (`Ran 75 tests in
  1.167s — OK`), after applying all 87 migrations on an empty SQLite database.
  No Postgres-specific code exists (no `contrib.postgres`, `ArrayField`,
  `JSONField` or raw SQL).
- Phase 0 added 13 tests (SQLite pragmas, profile picture upload/crop,
  analytics endpoint authorization) → 88 tests, green on Python 3.10.
- Phase 1 replaced the blog tests with sign-up on/off tests → 90.
- Phase 2 added `reviews/tests/services/` (73 service tests with golden
  `.bib` samples in `reviews/tests/data/`) and conducting view tests for
  import, bulk actions, QA, extraction, duplicates and exports → 175 tests;
  the service layer is at 94 % line coverage.
- Phase 3 added `parsifal/api/tests/` (auth, tokens, users, every router,
  OpenAPI operationId uniqueness, and the end-to-end
  `test_e2e_full_review.py`), token model/view tests and management command
  tests → **217 tests**; the API package is at 98 % line coverage.
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

1. The **planning** AJAX views (~36 endpoints) still have no view tests; the
   rules behind them are now covered through `services/protocol`,
   `services/quality` and `services/extraction` tests, and the API will call
   those services directly.
2. ~~Business rules untested~~ — covered in phase 2 (final selection,
   duplicates, search string, scores, coercions, import mapping).
3. ~~Import/export untested~~ — covered in phase 2 (service and view level);
   DOCX content assertions are still shallow.
4. **Authorization** of the remaining legacy planning endpoints that take
   child ids is untested (see [13-known-issues.md](13-known-issues.md) §B).

## Testing policy for new work

Everything added by the fork must ship with tests, following the existing
style unless noted:

| Component | Test type | Notes |
|-----------|-----------|-------|
| Service layer (`parsifal/apps/*/services.py`) | Unit tests with factories, no HTTP | Cover every rule listed in the gaps above as the service functions are introduced. |
| HTTP API (`parsifal/api/`) | `ApiTestCase` (`parsifal/api/tests/base.py`): author/co-author/outsider/admin users with Bearer tokens, `self.api(method, path, payload)` helper | One test module per router; assert status, JSON shape, permission denials (403/404), and DB side effects. `test_auth_and_accounts` checks the OpenAPI document and operationId uniqueness. |
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
