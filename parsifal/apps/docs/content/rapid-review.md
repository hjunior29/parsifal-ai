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
```

`PATCH /api/v1/reviews/{id}` takes `demand`, `demand_notes`,
`practical_problem`, `practical_context`, `stakeholder_roles`, `started_on`,
`deadline`; `GET /reviews/{id}/checklist?catalog=rapid`,
`PUT /reviews/{id}/checklist/{key}`, `POST /reviews/{id}/threats/draft`.
