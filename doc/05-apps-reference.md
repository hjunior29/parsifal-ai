# 05 — Django Apps Reference

One section per app under `parsifal/apps/`. "Fork disposition" follows the
decisions in [decisions.md](decisions.md): **Keep**, **Keep (trim)**, or
**Remove**.

| App | Lines (py, excl. migrations) | Tests | Disposition |
|-----|------------------------------|-------|-------------|
| `reviews` (+ `planning`, `conducting`, `reporting`, `settings`) | 3 913 | 297 | Keep — core |
| `library` | 819 | 0 | Keep — service layer + API/CLI/MCP added 2026-10-16 |
| `invites` | 706 | 351 | **Removed 2026-10-16 (ADR-008)** — replaced by Review settings → Manage access |
| `authentication` | 586 | 229 | Keep (trim: no public sign-up, no reCAPTCHA) |
| `accounts` | 341 | 164 | Keep — pictures and public profile fields removed (ADR-008); hosts API tokens |
| `core` | 231 | 26 | Keep — trimmed in phase 1 (home page = review list; `Media` dropped) |
| `docs` (new, phase 9) | — | 6 | In-app documentation of the fork's features at `/docs/`, Markdown content under `content/`. |
| `api` (new, phase 3; `parsifal/api/`) | — | 50+ | JSON API v1 — see [14-api.md](14-api.md). |
| `blog` | 179 | 67 | **Removed in phase 1** |
| `help` | 162 | 0 | **Removed in phase 1** (in-app docs return in phase 9) |
| `activities` | 146 | 0 | **Removed in phase 1** |

The sections below describe the apps as inherited; phase 1 changes are noted
inline.

---

## `reviews`

**Responsibility.** The review aggregate: `Review`, `Source`, protocol
entities, `Article` and everything attached to it (see
[03-domain-model.md](03-domain-model.md)). Also review creation, the review
overview page, co-author removal/leave, and the shared authorization helpers.

| Element | Location |
|---------|----------|
| Models | `reviews/models.py` |
| Views | `reviews/views.py` — `reviews` (user's list), `new`, `review`, `remove_author_from_review`, `save_description`, `leave` |
| Forms | `reviews/forms.py` — `CreateReviewForm`, `ReviewForm` |
| Guards | `reviews/decorators.py` (`author_required`, `main_author_required`), `reviews/mixins.py` (`ReviewMixin`, `MainAuthorRequiredMixin`, `AuthorRequiredMixin`) |
| Admin | `reviews/admin.py` — `ReviewAdmin` |
| URLs | `reviews/urls.py` (namespace `reviews`) includes planning/conducting/reporting |
| Templates | `templates/reviews/{new,review,review_header,reviews}.html` |
| Static | `static/js/review.js` |
| Fixtures | `fixtures/source_initial_data.json` |
| Tests | `tests/test_new_review_view.py`, `tests/test_reviews_view.py`, `tests/factories.py` |

### `reviews.planning`

Protocol editing. All logic is in `planning/views.py` (870 lines, ~36 AJAX
views grouped by section: objective, questions, PICOC, keywords/synonyms,
search string, sources, criteria, quality assessment, data extraction).
`planning/forms.py` has `KeywordForm`/`SynonymForm` (the only Django forms in
the phase). Templates: `protocol.html`, `quality_assessment_checklist.html`,
`data_extraction_form.html`, `planning_header.html`, and `partial_*.html`
fragments. JS: `planning_{question,picoc,keyword,search_string,source,criteria,quality_assessment,data_extraction}.js`.
No tests.

### `reviews.conducting`

Search strings per source, Scopus search, BibTeX import, study selection,
duplicates, quality assessment, data extraction, analysis data, XLS exports.
`conducting/views.py` (1 303 lines) also contains the HTML-building helpers
`build_quality_assessment_table`, `build_data_extraction_table`,
`build_data_extraction_field_row`, `build_article_table_row`, and the import
helpers `bibtex_to_article_object`, `_import_articles`. Templates
`conducting_*.html` + `partial_conducting_*.html`; JS
`conducting_{search_studies,import_studies,study_selection,quality_assessment,data_extraction,data_analysis}.js`.
One placeholder test.

### `reviews.reporting`

`reporting/export.py: export_review_to_docx` and `reporting/views.py`
(`reporting`, `export`, `download_docx`). Templates `export.html`,
`reporting.html`, `includes/header.html`. One test (page renders).

### `reviews.settings`

Rename (`settings`), `transfer`, `DeleteReviewView`; `ReviewSettingsForm`
(`name` only). Templates `review_settings.html`, `includes/menu.html`. Tests
for delete.

**Fork notes.** Keep intact. Introduce `reviews/services/` (or
`services.py` per sub-app) and move rules out of views progressively; the API
calls services, never views. Register remaining models in admin for
self-hosted troubleshooting.

---

## `library`

**Responsibility.** Per-user bibliography independent from reviews:
`Document` (full BibTeX record), `Folder`, `SharedFolder`/`Collaborator`,
`DocumentFile`. Views in `library/views.py` (416 lines): listing with search,
ordering and pagination; folder CRUD; document create/edit via JSON+HTML
modals; move/copy/remove/delete bulk actions; BibTeX import. Templates in
`templates/library/`, JS `library.js` (330 lines). Since 2026-10-16 the same
operations exist in `library/services.py` (owner-scoped; tested) and in the
API (`/api/v1/library/…`, see [14-api.md](14-api.md)), and every legacy view
lookup is scoped to `request.user`. Shared folders remain UI-only and
half-built upstream (no way to add collaborators). No admin
registration (admin exists only for `reviews.Review`, `invites.Invite`,
`core.Media`, `blog.Entry`, `help.Category`/`Article`).

**Fork notes.** Keep. Useful later as the place where an agent can stage
BibTeX corpora before attaching them to a review, and where full-text files
(`DocumentFile`) could be stored for AI reading. Not part of API v1 unless
cheap. Fix missing ownership checks (`folder`, `document`).

---

## `invites`

**Responsibility.** Invite a person (existing user or e-mail) to co-author a
review. `Invite` model with `accept()`/`reject()`; `SendInviteForm` sends an
e-mail (`invite_email.html`) with the `/invites/<code>/` link via
`EmailMultiAlternatives`; class-based views `ManageAccessView`,
`InviteDeleteView`, `InviteDetailView`, `UserInviteListView`,
`AcceptUserInviteView`, `RejectUserInviteView`; `templatetags/`. 351 lines of
tests — the reference for test style.

**Fork notes.** Keep as the membership mechanism, but: the "contacts" dropdown
depends on `activities` (people you follow) — replace with a plain user picker;
e-mail sending becomes optional (console backend by default). The API should
offer a direct `add co-author` for admins in addition to invites.

---

## `authentication`

**Responsibility.** `Profile` model (+ `post_save` signals), `SignUpView`,
`SignUpForm` (invite auto-accept, reCAPTCHA), `CaseInsensitiveUsernameOrEmailModelBackend`,
validators (`ASCIIUsernameValidator`, forbidden usernames = URL prefixes,
case-insensitive uniqueness of username/e-mail). Tests: 229 lines.

**Fork notes.** Keep `Profile`, backend and validators. Sign-up becomes
disabled by default (setting) — the admin creates users or the CLI does.
Remove reCAPTCHA. `Profile.get_followers*` helpers go with `activities`.

---

## `accounts`

**Responsibility.** Account settings pages: profile, e-mail, picture upload
and crop (`Pillow`, `Jcrop`). Tests: 164 lines.

**Fork notes.** Keep. Fix `Image.ANTIALIAS` (removed in Pillow 10; see
known issues). This is where "API tokens" settings page will live.

---

## `core`

**Responsibility.** `home` view (cover vs. dashboard with feed + latest blog
entry), `LoginRedirectView`, `Media` model (Open Graph tags for help
articles), `settings` context processor, `StaticSitemap`, management commands
`environment` and `release`, templates `core/{about,cover,home,support}.html`.

**Fork notes.** Keep the app; simplify `home` to the review list (no feed, no
blog), drop `Media` with `help`, keep context processor (minus analytics /
recaptcha / sentry keys). Add bootstrap management commands here
(`init`, `create_api_token`, `load_default_sources`).

---

## `blog`, `help`, `activities` — Removed (phase 1, 2026-10-15)

- `blog`: `Entry` model, list/detail views, sitemap; linked from header and
  home.
- `help`: `Category`/`Article` models, article pages with view counter and
  search; `Media` OG tags; linked from header and from in-app help links.
- `activities`: `Activity(FOLLOW)`, follow/unfollow endpoints, follower lists;
  consumed by `core.home` feed, `reviews.views.reviews` (follower counts on the
  profile page), `invites.SendInviteForm` (contacts), `Profile` helpers.

What was done: the three apps were deleted with their migrations (no other
app's migration graph referenced them); `core.Media` was removed by
`core/migrations/0003_delete_media.py`; `Profile` lost its follower helpers;
`core.home` renders only the user's reviews; `reviews.views.reviews` no longer
shows follower counts; `invites.SendInviteForm.invitee` lists every active
user instead of "people you follow"; `utils/recaptcha.py`, Google Analytics
and Sentry were removed; `PARSIFAL_ALLOW_SIGNUP` gates `/signup/`.
Databases created by upstream keep orphan `blog_*`, `help_*` and
`activities_*` tables.

---

## `parsifal/utils`

| Module | Purpose | Disposition |
|--------|---------|-------------|
| `elsevier/client.py`, `elsevier/exceptions.py` | Scopus/ScienceDirect REST client | Keep (optional feature) |
| `recaptcha.py` | Google reCAPTCHA verification | Remove |
| `ipaddress.py` | `get_remote_ip_address` (X-Forwarded-For) | Keep (used by recaptcha only today; useful for API audit logs) |
| `mask.py` | `mask_email` for invite landing page | Keep |
| `test.py` | `login_redirect_url` helper for tests | Keep |
| `version.py` | PEP 440 version rendering | Keep |

## `parsifal/templates` and `parsifal/static`

Project-level `base.html` (Bootstrap 3 layout, GA/Sentry snippets in
production, global modal and page-loading spinner, compressed CSS/JS),
`includes/{header,footer,messages}.html`, error pages, `form_vertical.html`,
`registration/*`, `admin/base_site.html`. Static: vendor Bootstrap, Font
Awesome, jQuery plugins (tablesorter, fileupload, Jcrop, expanding,
mustache), `parsifal.css` (507 lines), `parsifal.js` (211 lines: tooltips,
check-all tables, ajax button states, spinners, `pageLoading`).
