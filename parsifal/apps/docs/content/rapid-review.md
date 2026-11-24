# Rapid reviews

A **rapid review** follows Cartaxo, Pinto & Soares (2020), *Rapid Reviews in
Software Engineering*: a secondary study conducted **with practitioners**,
bounded to a **practical problem** inside their context, that cuts cost and
time **on purpose** (days or weeks) and reports in a medium practitioners read
(an Evidence Briefing). It is not an ad-hoc review: it has a protocol, and every
concession made to be rapid is documented in it, with why.

Choose *Rapid review* as the type when creating the review, or later in
*Review settings*. What follows exists only in rapid reviews; systematic
literature reviews and mapping studies do not change.

## Practical context (Planning → Protocol)

Above the objectives, the **Practical Context** of the review (Cartaxo et al.
2020, §4.1):

| Field | What it says |
|-------|--------------|
| Demand | How the demand arose: practitioners asked for it; the researcher aligned their agenda with practitioners' needs; the researcher prospected a practical problem; policy makers or the organisation asked for it; other |
| How the demand arose | Who asked, and why now |
| Practical problem | The problem as defined with the practitioners, and how (interviews, a focus group…) |
| Context | The organisation, project, team and their constraints |
| Stakeholders and their roles | Who takes part and how much (practitioners usually have no account) |
| Start date, deadline | The time frame |

Below the selection criteria, the **Procedures**: the selection procedure (for
instance, three rounds and one researcher) and the synthesis strategy (a
narrative synthesis, a thematic analysis). The research questions' help adds
the two kinds of questions of a rapid review: exploratory and motivational.

## Rapid Review Checklist (Planning)

A tab of its own lists the **collaboration with the practitioners** (problem,
questions and protocol defined or validated with them; doubtful studies shown
to them; findings discussed in a workshop; follow-up on adoption) and the
**concessions** made to be rapid ([G] §4.2): a single search source, limits by
date, language, area or method, peer-reviewed literature only, one reviewer, a
title-only first round, quality not appraised, one extractor, studies with
missing data excluded, a narrative synthesis… and the reporting (Evidence
Briefing, protocol made available, a scientific venue).

The concessions are a menu, not a package: tick what the review does and write
why. Each concession shows the threat to validity it brings. **Save and draft
the threats to validity from the concessions** adds one threat to
[Reporting → Threats to Validity](/docs/reporting/) per concession ticked —
its type, the threat, and its justification as the mitigation. It only adds:
a threat the review has already (same name) is left alone.

A change to the checklist once studies were imported is an amendment to the
protocol in the [History](/docs/history/).

## Screening rounds (Conducting → Study Selection)

A rapid review may screen in three rounds ([G] §4.2.2; in [E], 1,973 → 84 →
47 → 17 studies): the **titles** only, to discard what is clearly out of scope
without reading the abstracts; then the **titles and abstracts**; then the
**full text**. Its decisions have the three stages, the first one being the
title round (the other reviews keep two).

The study list has a **Round** control next to *Show*:

- *Every study* is the list as in any review;
- with a round chosen, the list holds the studies of that round, *To screen*
  (not decided by you there yet), *Screened* (decided by you) or every one: at
  the title round every study but the duplicates; at a later round, those
  decided there and those accepted at the round before (its queue);
- in a round, **accepting or rejecting a study is also your decision at that
  round**, with the same criterion — from the Action menu (one study, a page, or
  *Select all N studies*) or the study's window — in one change of the
  History; back to unclassified, your decision there goes;
- at the title round the abstract column is left out and the study's window
  keeps the abstract a click away.

Studies accepted before the rounds (with no decision at the title round) show
only in the title round, where they can be decided in bulk.

**Reviewer agreement** compares and consolidates the decisions of each round,
the title round included.

**Exclude, Include and Screen with AI** screen at a round: *Title screening*
(its default request sends the title only, and asks from it alone) or *Title
and abstract screening*; *Only the studies of the round the reviewer has not
screened yet* narrows what is sent. The run's decisions are recorded at its
round; undoing it restores them there.

**Data Analysis → Study Selection** has the **Selection Rounds**: the records
after duplicates, those that passed the title round, the title-and-abstract
round, and those included at the full text, with what each round has not
decided yet. The PRISMA 2020 diagram counts both rounds as the screening and
splits the records excluded by round.

## Elsewhere

- The **progress bar** has one more step: the practical problem. Quality
  assessment counts only when the review has a checklist (a rapid review may
  skip it, as a concession).
- The **report** (.docx) has the *Practical Context* and the *Rapid Review
  Checklist* sections.
- The **Evidence Briefing** is written outside Parsifal and uploaded to
  *Reporting → Manuscripts* like any other text.

## In the API, the CLI and the MCP server

```
parsifal review create --title "Flaky tests" --review-type rapid
parsifal review update --review alice/flaky-tests --demand practitioners \
  --practical-problem "Flaky tests slow the team down." --started-on 2026-11-23 --deadline 2026-11-30
parsifal checklist get --review alice/flaky-tests --catalog rapid
parsifal checklist set --review alice/flaky-tests --key rr_single_source --applied --notes "Scopus indexes the main venues"
parsifal threat draft --review alice/flaky-tests
parsifal article list --review alice/flaky-tests --stage title --stage-state pending
parsifal article set-status --review alice/flaky-tests --ids 12 --ids 13 --status R --selection-criteria-id 4 --stage title
parsifal ai-screening run --review alice/flaky-tests --stage title --pending --reviewer-id 7
parsifal analytics funnel --review alice/flaky-tests
```

`PATCH /api/v1/reviews/{id}` takes `demand`, `demand_notes`,
`practical_problem`, `practical_context`, `stakeholder_roles`, `started_on`,
`deadline`; `GET /reviews/{id}/checklist?catalog=rapid`,
`PUT /reviews/{id}/checklist/{key}`, `POST /reviews/{id}/threats/draft`.
`GET /reviews/{id}/articles?stage=&stage_state=`, `POST /articles/status`
with `stage` (and `match_stage`, `match_stage_state` for `all_matching`); the
decisions take `stage` `title` and default to the first round; the AI
screening start, preview, impact and rerun take `stage` and `pending`;
`GET /reviews/{id}/analytics/funnel`; the PRISMA has `excluded_by_round`.
