# 17 — Rapid reviews (Cartaxo, Pinto & Soares 2020): plan

**Status:** implemented on 2026-11-24, phases 1 and 2 (§4); ADRs in
`doc/decisions.md`. Decisions taken by Helder on 2026-11-24 (§6). Where the
implementation differs from this plan, §7 says so.

Sources:

- **[G]** Cartaxo, B., Pinto, G., Soares, S. (2020). *Rapid Reviews in Software
  Engineering*. arXiv:2003.10006. This is **the guideline**: §4 is the
  process (planning, performing, reporting).
- **[E]** Cartaxo, B., Pinto, G., Soares, S. (2018). *The Role of Rapid Reviews
  in Supporting Decision-Making in Software Engineering Practice*. EASE '18.
  doi:10.1145/3210459.3210462. This is **the worked example** that [G] §4.1.5
  points to: a complete RR protocol (§4), its threats (§4.8) and what the
  practitioners asked to improve (§5.2).

## Scope: what to implement, and nothing more

1. **Review type `rapid`** (§3.1).
2. **Practical context in the protocol**: demand, problem, context,
   stakeholder roles, time frame (§3.2).
3. **The three protocol texts on the Protocol page**: selection procedure,
   synthesis strategy, validity threats (§3.3).
4. **Rapid review checklist**: collaboration with practitioners and
   methodological concessions, each with a justification, plus a button that
   drafts the validity threats from them (§3.4).
5. **A title-only screening round** before the title-and-abstract one, with
   a round mode on Study Selection, AI runs per round, and the funnel and
   PRISMA showing the round (§3.5).
6. **The .docx** exports the practical context and the checklist (§3.6).

All of it exists **only in reviews of type `rapid`**. SLR and mapping reviews
do not change.

**Not in this work:**

- The **Evidence Briefing**, the findings and the recommendations. The
  briefing ([G] §4.3.1) is written outside Parsifal. It will be one of the
  final texts of the review, uploaded to a "final texts" screen that Helder will
  build separately. That screen does not exist yet. Parsifal does not generate
  the briefing, and no hint about it is added now.
- Everything in §5.

## 0. Where Parsifal stands (SLR and mapping)

There is one workflow. `Review.review_type` (`slr` | `mapping`,
`reviews/models.py:72`) is a **label**. It changes:

- the badge in `reviews/templates/reviews/review_header.html:8`;
- the Type column in `reviews/templates/reviews/reviews.html:33` and
  `core/templates/core/home.html:29`;
- the type paragraph of the .docx (`reporting/export.py:11`).

Nothing is gated by it. The mapping additions (test set, Petersen
checklist, search documentation) are optional for any review, and most have
no web UI.

Screening has two stages (`StudyDecision.TITLE_ABSTRACT`, `FULL_TEXT`,
`models.py:841`). `Article.status` is the consolidated decision. A study's
status and its decision per stage are set separately:

- the status on Study Selection or the Details tab;
- the decision on the Reviewers tab.

**Rapid reviews differ** (Helder, 2026-11-24): what is specific to a rapid
review exists only when `review_type == "rapid"`.

## 1. What a rapid review asks of the tool

The core aspects in [G] §2.1 are:

1. It is conducted with practitioners, bounded to a practical problem, inside
   their context.
2. It cuts cost and time on purpose: days or weeks, not months or years ([G]
   Table 1).
3. It is reported in a medium that appeals to practitioners: the Evidence
   Briefing ([G] §4.3.1). This happens outside Parsifal (see Scope).

It is **not** an ad-hoc review. It has a protocol. Every concession is
documented in that protocol ([G] §2.1). "Transparency is the golden standard"
([G] §4.2).

The concessions are a **menu, not a package**. For example, one RR keeps
several search sources but skips quality appraisal, while another uses one
source and appraises quality rigorously ([G] §4.2). The tool records *which*
concessions were made and *why*; it does not enforce a set.

## 2. Coverage: the guideline against this plan

| [G] § / [E] § | Element | Parsifal today | This plan |
|---|---|---|---|
| 4.1.1; E 7.2 | Demand: practitioners ask; researcher aligns their agenda; researcher prospects a problem (E: also policy makers) | — | Demand (§3.2) |
| 4.1.2; E 3.2.1 | Practical problem, defined with practitioners (interviews, focus group) | `objective` only | Problem and context (§3.2) |
| 4.1.3; E 7.1 | RQs defined with practitioners; exploratory and motivational questions | `Question` | Help text (§3.2) |
| 4.1.4 | Stakeholder roles and level of participation | co-authors and agents (accounts) | Roles (§3.2) |
| 4.1.5 | Protocol changes documented and justified | History marks amendments | As is; justification later (§5) |
| Table 1 | Time frame: days or weeks | — | Start date and deadline (§3.2) |
| 4.2 | Every concession, limitation and threat in the protocol | `validity_threats` (API only) | Checklist (§3.4); texts on the web (§3.3) |
| 4.2.1 | One source + snowballing; limits by date, language, geography, research method | sources, `SearchSession` | Concessions (§3.4) |
| 4.2.2 | Restrictive context criteria; one reviewer; second reviewer on a sample; **title-only first round** | criteria; kappa; two stages | Title round (§3.5); sample later (§5) |
| E 4.4 | Doubtful studies shown to the practitioners | comments, star | Checklist item (§3.4) |
| 4.2.3 | QA skipped, only rigorous venues, one reviewer, or pairs on a sample | QA optional already | Concessions (§3.4) |
| 4.2.4 | One extractor; studies with missing data excluded and reported | `DataExtraction.user` | Concession + a full-text exclusion criterion (§3.4) |
| 4.2.5 | Light synthesis, recommendations | — | In the final text, outside Parsifal |
| 4.3.1 | Evidence Briefing | — | Outside Parsifal (final text, uploaded later) |
| 5.3 | Peer-reviewed literature only | — | Concession item (§3.4) |
| E 4.4 Fig. 1 | Rounds: 1,973 → 84 (title) → 47 (abstract) → 17 (full text) | PRISMA with two stages | Funnel + PRISMA (§3.5) |

## 3. Changes

### 3.1 The review type `rapid`

- `Review.RAPID = "rapid"`; `REVIEW_TYPES` gains `(RAPID, _("Rapid review"))`.
  `max_length=10` fits. This needs a migration, because the choices change.
- `Review.is_rapid_review` property. It is the switch for everything below.
- Make the three labels three-way. Today they read `if is_mapping_study … else
  "Literature review"`: `review_header.html:8`, `reviews.html:33`,
  `home.html:29`.
- Build the error message from `REVIEW_TYPES` instead of hardcoding it:
  `services/reviews.py:122-124` ("review_type must be 'slr' or 'mapping'").
- Change the CLI help strings to "slr, mapping or rapid"
  (`clients/parsifal-cli/parsifal_cli/operations.py:126,429`); also the API
  schema docs.

**Changing the type:**

- To `rapid`: always allowed.
- From `rapid` to another type: refused (422) while title-round decisions
  exist, because other types have no title round.
- The RR fields and checklist items are kept and simply not shown. Nothing is
  deleted.

### 3.2 Protocol: practical context

New optional fields on `Review`, edited on Protocol in rapid reviews and
recorded by `history.Kind` like the other protocol fields:

| Field | Type | From |
|---|---|---|
| `demand` | choice: practitioners asked · researcher aligned their agenda · researcher prospected a problem · policy makers/organisation · other | [G] 4.1.1, [E] 7.2 |
| `demand_notes` | text | how the demand arose |
| `practical_problem` | text | [G] 4.1.2: the problem as defined with the practitioners and how (interviews, focus group) |
| `practical_context` | text | [E] 3.1: organisation, project, team, constraints |
| `stakeholder_roles` | text | [G] 4.1.4: who does what, level of participation (practitioners usually have no account) |
| `started_on`, `deadline` | dates | [G] Table 1 time frame; [E] "one week, one researcher full time" |

UI:

- A **Practical context** section on Protocol, above Objective.
- Its help modal cites [G] 4.1.
- The research questions' help modal adds, in rapid reviews, the two kinds of
  [E] §7.1:
  - exploratory: "What are the strategies to …?";
  - motivational: "What are the benefits of / problems caused by …?".

### 3.3 The protocol texts on the web

`selection_procedure`, `synthesis_strategy` and `validity_threats` exist in the
model, the API and the .docx (`reporting/export.py:141`), but not on the
Protocol page. In rapid reviews, show them as three text panels on Protocol:

- the selection procedure says "three rounds, one researcher";
- the synthesis strategy says "narrative" (or thematic analysis, as [E] §4.6);
- the validity threats hold the concessions (§3.4).

### 3.4 Rapid review checklist: collaboration and concessions

Reuse `ProcessChecklistItem` (`models.py:819`: `review`, `key`, `applied`,
`notes`, unique per review and key), as the Petersen checklist does
(`services/mapping.py:13`).

**Code**

- `mapping.checklist(review)` becomes `checklist(review, catalog)`, with
  catalogs `petersen` (today's) and `rapid` (new).
- Keys must not clash between catalogs.
- API, CLI and MCP take `catalog`. The default stays `petersen` for
  compatibility.

**The `rapid` catalog**

The format is `(key, group, label, threat)`. `threat` is the default sentence
for the limitations; it is empty for non-concessions. Each item's `notes` is
the justification.

- **Collaboration** ([G] 4.1, [E] 3–4):
  - problem defined with practitioners;
  - questions defined with practitioners;
  - protocol validated with practitioners;
  - search string refined with practitioners ([E] 4.3 feedback loop);
  - doubtful studies shown to practitioners ([E] 4.4);
  - findings discussed with practitioners in a workshop ([E] 3.2.3, 5.2);
  - follow-up on adoption ([E] §6, two months later).
- **Search** ([G] 4.2.1):
  - a single source — "Only one search engine was used, which may limit the
    primary studies found" ([E] 4.8);
  - snowballing to complement the source;
  - limited by date;
  - limited by language;
  - limited by geographical area;
  - limited by research method;
  - peer-reviewed literature only ([G] 5.3).
- **Selection** ([G] 4.2.2):
  - one reviewer — "may introduce selection bias";
  - a second reviewer on a sample;
  - criteria restricted to the practical context ([G]: not necessarily a
    threat, contextualised evidence is good practice);
  - a title-only first round — "relevant studies may be lost because of their
    titles".
- **Quality** ([G] 4.2.3):
  - not appraised — "may limit the reliability of the evidence";
  - only venues with rigorous review;
  - one appraiser;
  - pairs on a sample.
- **Extraction** ([G] 4.2.4):
  - one extractor;
  - studies with missing data excluded, authors not contacted.
- **Synthesis** ([G] 4.2.5): narrative synthesis instead of a formal method.
- **Reporting** ([G] 4.3, 5.2):
  - Evidence Briefing;
  - protocol and list of primary studies made available;
  - also reported in a scientific venue.

**Web UI**

- Planning gains a tab **Rapid review checklist**, in rapid reviews only.
- Each item has a checkbox and a justification, grouped as above.
- Below the list, a button **Draft the validity threats from the concessions**
  appends, never overwrites, one line per applied concession (threat +
  justification) to `validity_threats`. That change is a normal History event.

**Missing data:** for [G] 4.2.4, the implementer only documents the "exclude
for missing data" practice: a full-text exclusion criterion such as
"Insufficient data". No new mechanism is needed.

### 3.5 Screening rounds: title → title and abstract → full text

**What the guideline says.** [G] §4.2.2: an RR may split selection into three
substeps. The first on **titles only** discards clearly out-of-scope studies
without reading their abstracts, at the risk of false negatives, which must be
reported. Then comes the abstract, then the full text. [E] §4.4: 1,973 → 84 →
47 → 17, with one researcher.

**Decision (Helder).** The second round is the **existing title-and-abstract
stage**. No abstract-only stage is created. The guideline gives no reason to
hide the title there, and in [E] the second round read the abstracts of
studies whose titles had already been read. There is no "partial text" round.

**Model**

- `StudyDecision.STAGES` gains `TITLE = "title"` ("Title screening"), before
  `TITLE_ABSTRACT`.
- A model helper `review.stages()` returns:
  - for `rapid`: `title`, `title_abstract`, `full_text`;
  - otherwise: `title_abstract`, `full_text`.

**Validation**

- `decisions._validate_stage` (`services/decisions.py:53`) validates against
  `review.stages()`. `title` is refused outside rapid reviews.
- Every default `stage=TITLE_ABSTRACT` becomes "the review's first stage":
  - `services/decisions.py:66,101,118,228,257,305`;
  - API `routers/decisions.py:54,79,92` and `schemas/decisions.py:27,50`;
  - web `conducting/views.py:722,786,802`;
  - CLI `operations.py:1581,1598,1610`.
- `decisions.summary` (`:370`) loops over `review.stages()`.
- The stage selects in the Reviewers tab
  (`partial_conducting_article_decisions.html`, context in
  `conducting/views.py:_decisions_context`) and in the agreement panel list
  `review.stages()`. Kappa and consolidation work per stage as now.

**Round mode on Study Selection (rapid only)**

Today a reviewer sets a study's status *and* records the decision per stage on
the Reviewers tab. With three rounds and one reviewer that doubles the work.

- Study Selection gets a **Round** control next to the status filter:
  *Title · Title and abstract · Full text · All*. "All" is today's list.
- With a round chosen:
  - the list shows that round's studies, pending or decided (`stage`,
    `stage_state` filters in `services/studies.list_articles` and
    `selected_ids`, so "Select all N" works);
  - in the title round, the list and the study window show the title, with the
    abstract hidden. The rest stays one click away for doubtful cases;
  - every status change (row, bulk Action, Details) **also records the actor's
    decision at that round**, with the same criterion. That is one action and
    **one** History event: `set_status` and `record_decisions` today record one
    event each, so merge them when a round is given.
- Queue rule (proposal; pin it down with tests). For round *k* with previous
  round *k−1*:
  - **eligible(title)** = not duplicated;
  - **eligible(k)** = has a decision at *k*, OR (`status == A` and has a
    decision at *k−1* and none at *k*);
  - **pending(k) for the user** = eligible(k) and no decision by them at *k*.
- Studies accepted earlier without a decision show only in the title round.
  They can be bulk-recorded there.

**AI screening**

- Decisions today are recorded at `TITLE_ABSTRACT`
  (`services/ai_screening.py:1061,1069`), and undo and counts use it too
  (`services/ai_runs.py:108,334`). Use the run's stage instead:
  `ScreeningRun.parameters["stage"]`. Runs without it count as
  `title_abstract`.
- In rapid reviews, the setup window and the API, CLI and MCP offer the round:
  *Title* or *Title and abstract*. Other reviews have no choice, as today.
- The default request template of the title round sends `{{study.title}}`
  only, and its task says "from the title of a study"
  (`services/screening_requests.py`). Templates stay editable by the user.
- Scope: besides `statuses`, a run can send "the studies pending in the round"
  (`eligible_articles`, `services/ai_screening.py:353`).
- The earlier AI decisions stay:
  - Include with AI never rejects;
  - passes are recorded as U;
  - one kappa per stage.

**Data Analysis (rapid only)**

- **Selection funnel:** records after duplicates, then studies passing the
  title round, the title-and-abstract round and the full text, as [E] Fig. 1.
  The numbers also come through the API, CLI and MCP.
- **PRISMA 2020** (`services/analytics.py:prisma`):
  - "Records screened" covers both screening rounds;
  - "Records excluded" is split by round ("at the title n, at the title and
    abstract n"), taken from the stage of the rejecting decision;
  - the automation split (`:332`) uses both screening rounds;
  - the full-text logic stays.

### 3.6 Report (.docx)

Add `practical_context` and `rapid_checklist` to `DOCX_SECTIONS`
(`services/reports.py`) and `reporting/export.py`. Offer them in the export
window (`reporting/export.html`) of rapid reviews. The checklist heading at
`export.py:273` ("Process Evaluation (Petersen et al. 2015)") must name its
catalog.

### 3.7 Cross-cutting rules (from earlier decisions)

- Every new write path records through a `history.Kind` or helper, or the
  History gets a hole (`plan-review-history`).
- Every new API operation gets a registry entry in
  `clients/parsifal-cli/parsifal_cli/operations.py`; otherwise the parity test
  (`parsifal/api/tests/test_cli_parity.py`) fails.
- New `Review` fields go into backups automatically (concrete fields).
- Bump `?v=` on every changed static file.
- Docs:
  - `parsifal/apps/docs/content/rapid-review.md` plus a row in `index.md`;
  - an ADR in `doc/decisions.md`;
  - a newsfragment.
- Tests for each service. Run:
  - `SECRET_KEY=test .venv/bin/python manage.py test --settings=parsifal.settings.tests`;
  - `.venv/bin/python -m pytest -q clients/parsifal-cli`.

## 4. Order of work

| Phase | Content | Size |
|---|---|---|
| 1 | §3.1 type; §3.2 practical context; §3.3 protocol texts; §3.4 checklist + draft of the threats; §3.6 .docx | small–medium |
| 2 | §3.5 title round: stage, validation, Reviewers tab, agreement, round mode, AI runs per round, funnel, PRISMA | large |

## 5. Later (not in this work)

Helder wants to know about these, but not now:

- **When the "final texts" screen exists:** in rapid reviews, a hint to upload
  the Evidence Briefing there. Not even the hint is added now.
- Findings and recommendations inside Parsifal, linked to studies ([G] 4.2.5).
- The round mode and the protocol texts for SLR and mapping reviews.
- A justification next to a protocol amendment in the History ([G] 4.1.5,
  PRISMA 2020 item 24c). Events are immutable, so it would be a linked event.
- `Question.kind` (exploratory, motivational).
- A random sample of studies for a second reviewer ([G] 4.2.2, 4.2.3).
- A web UI for the Petersen checklist (same component as §3.4).
- The review's duration in the header ("day 4 of 7").
- Practitioner accounts with a read-only role ([E] 4.4).

## 6. Decisions (Helder, 2026-11-24)

1. No "partial text" round.
2. What is specific to a rapid review exists only in rapid reviews; SLR and
   mapping stay as they are.
3. The rounds are title → title and abstract (the existing stage) → full
   text. There is no abstract-only round.
4. The Evidence Briefing is not generated by Parsifal. It is one of the
   review's final texts, uploaded later to a screen Helder will build
   separately.
5. The improvements in §5 are for later.

## 7. As implemented (2026-11-24)

Everything in §3 is in, for rapid reviews only, with these differences:

- **Threats to validity.** The same day, Reporting gained a list of threats to
  validity of its own (`ValidityThreat`: type, name, description, mitigation)
  for every review. So the "draft" button of the checklist (§3.4) adds one
  `ValidityThreat` per concession applied (its suggested type, the threat, the
  justification as the mitigation), skipping a threat of the same name,
  instead of appending lines to the `validity_threats` text; and §3.3 shows the
  selection procedure and the synthesis strategy on Protocol, with a link to
  the threats rather than a text panel for them. The checklist page saves
  before drafting.
- **Final texts.** The "final texts" screen of the Scope exists now:
  Reporting → Manuscripts (any name, versions). The Evidence Briefing is
  uploaded there like any text; no hint was added (§5).
- **Progress.** A progress bar was added the same day; a rapid review has a
  step of its own there, its practical problem.
- **Round mode.** Bulk actions, *Select all N studies* and the study's window
  give the round with the status. In the title round, the abstract column of
  the list is left out and the study's window keeps the abstract a click
  away. Back to unclassified removes the reviewer's decision at the round; a
  duplicate records none.
- **AI runs.** `pending` narrows the statuses chosen (it does not replace
  them). Choosing another round in the window restores that round's default
  request.
- **PRISMA.** A study rejected without a decision at any round counts as
  excluded at the title and abstract. The funnel (§3.5) is "Selection Rounds"
  on Data Analysis and `GET /analytics/funnel`.
- **Migrations:** `reviews.0057` (type and practical context), `reviews.0058`
  (the title stage).

