# Exclude and include with AI (Jev)

Study selection by a model, in two phases, in the name of a reviewer you choose:

1. **Exclude with AI**: Jev rejects the studies that clearly meet one of the
   review's **exclusion criteria**. One criterion is enough.
2. **Include with AI**: Jev accepts the studies that clearly meet **every**
   **inclusion criterion**, rejects those that clearly fail one, and leaves the
   rest unclassified for you.

[Jev](https://docs.typesafe.ai/models) is TypeSafe's decision model: it does not
write text, it returns the probability of each allowed answer (of yes, for a
yes/no question).

## Setting it up

1. Create an API key in your TypeSafe account.
2. In **Settings → Integrations**, paste the key: the page asks Jev right away
   for the models that key can use and shows them in the **Default model**
   select. Choose one and save; from then on the list is asked again every time
   the page loads, so you can change the default whenever you want. Each run can
   still use another model. Prefer
   a pinned version (`jev-1.13.0`): aliases such as `jev-latest` change without
   notice and make the screening impossible to reproduce. **Test the key**
   checks that Jev accepts it.
3. Write the exclusion and inclusion criteria in **Planning**. Jev works best in English.

The key is stored encrypted (with a key derived from the instance's `SECRET_KEY`) and is never shown again in
full; if `SECRET_KEY` changes, save the Jev key again. Parsifal's own API tokens are stored as hashes, so not
even Parsifal can read them back. Calls are billed to the key.

## Running it

On **Conducting → Study Selection**, tab *All Sources*, click **Exclude with
AI** or **Include with AI**. The window is the same for both and shows what will
be sent:

- **Reviewer**: the member of the review the decisions are recorded as. The
  main author can choose anyone in the review (themselves or any AI agent);
  create more reviewers as agents in *Manage access*. One person can thus screen
  as several reviewers (for instance with different models or guidance) and
  compare them in *Reviewer agreement*.
- **Model**: the models Jev lists for your key, asked when the window opens,
  with your default selected.
- **Review context**: title, objective, research questions and PICOC, taken
  from the review. You can edit them for this run; the review is not changed
  and the run's log keeps what was sent.
- **Extra guidance** (optional): definitions or borderline cases that help apply
  the criteria.
- **Criteria**: from the protocol, read-only. Exclusion: options `E1`, `E2`…
  plus `none` ("no criterion clearly applies, or there is not enough
  information"). Inclusion: `I1`, `I2`…, one yes/no question each.
- **Thresholds** (default 0.9, from 0.5 to 0.99): how sure Jev must be.
  Exclusion has one, to reject. Inclusion has two: the **accept threshold**
  and the **reject threshold**, set separately (for instance accept only above
  0.95 but reject from 0.85).
- **Studies**: all sources or one, and the **statuses** to send — any mix of
  accepted, rejected, unclassified and duplicated (*All* checks every one). The
  default is rejected + unclassified for exclusion, so a second reviewer
  screens the same studies as the first one, including those the first one
  rejected; and unclassified + accepted for inclusion, the studies that are
  still in. Each status shows how many studies it has; nothing is skipped
  because it was screened before.

**Start screening** sends the studies a few at a time and shows the progress
until the run ends; there is no stop button. **Done** reloads the page.

If a run is interrupted — the page was closed, the connection dropped, Jev
refused the key or was unavailable — it keeps the studies it had left. The next
time you open the window it says where the run stopped and offers **Continue**,
which goes on with the settings the run started with (model, context,
thresholds, studies). Starting a new run, of either phase, discards the unfinished one.

## From the API, CLI and MCP

The same operations exist outside the web, one to one. Runs use the Jev key of
the account that calls them, so an agent with its own token needs its own key
(`parsifal integration jev set --api-key -` reads it from stdin) and can only
screen as itself.

```bash
parsifal integration jev set --api-key - --model jev-1.13.0   # Settings → Integrations
parsifal integration jev test
parsifal ai-screening setup --review R                        # what the window shows (reviewers, models, studies per status…)
parsifal ai-screening run --review R --reviewer-id U --model jev-1.13.0 --threshold 0.9 --guidance @notes.txt
parsifal ai-screening run --review R --reviewer-id U --statuses U --statuses R --statuses A   # statuses to send (default R and U)
parsifal ai-screening run --review R --reviewer-id U --phase inclusion --accept-threshold 0.95 --reject-threshold 0.85   # Include with AI (default A and U)
parsifal ai-screening runs --review R
parsifal ai-screening results --review R --id RUN --outcome excluded
```

`ai-screening run` starts a run and screens until it ends, printing the
progress. Ctrl-C, or an interruption from Jev, leaves the run waiting:
`ai-screening run --run RUN` continues it. The step-by-step operations are also
there: `start`, then `step --id RUN` until the run is no longer running.
In MCP, `parsifal_ai_screening_run` does the same in one call and says when to
call again with `run_id`. Context fields you leave out take the review's
values.

## What happens to each study: exclusion

For every study Jev receives the **title, keywords and abstract only** (never
authors, venue or affiliations). One multiple-choice question with the criteria
and `none` is asked in three option orders in the same request, because the
model tends to favour the first option when unsure; the answers are averaged.

Probabilities of the options add up to 1, so the probability that *some*
criterion applies is `1 − p(none)`, even when two criteria split it. Then:

- `1 − p(none)` ≥ threshold: the reviewer's decision is **rejected**, with the
  most probable criterion as the reason.
- otherwise: the reviewer's decision is **unclassified** ("no exclusion
  criterion").

Every study screened gets the reviewer's decision, visible in the article's
*Reviewers* tab with the probability in the comment. Recording the "no
criterion" decisions too is what lets two reviewers be compared: their
agreement counts the studies both kept, not only those both rejected. Running
again as the same reviewer rewrites its decisions.

The study's **status** (what the table shows) follows the decision only when
the study is unclassified, or was rejected by this same reviewer:

| Status before the run | Rejected by the run | No criterion |
|---|---|---|
| Unclassified | rejected, with the criterion (the reviewer is its last editor) | stays unclassified |
| Rejected by this reviewer | rejected, with the new criterion | back to unclassified |
| Rejected by someone else, accepted, duplicated | kept | kept |

So a second reviewer screens the first one's rejections without undoing them:
where they differ shows up in *Reviewer agreement*. A study someone classifies
while the run is going keeps that status. Studies that failed (for example,
with no title or abstract) keep the reviewer's previous decision.

## What happens to each study: inclusion

Every inclusion criterion gets its own **yes/no question** ("does the study
meet it?"), and Jev answers with the probability of yes, `p(meets)`; the
probability that it is not met is `1 − p(meets)`. There is no "unclear" answer:
doubt shows as a probability away from 0 and 1. Each question is asked twice in
the same request, with what a yes and a no mean in both orders, and the two
answers are averaged. All criteria must be met, so the **weakest** criterion
decides — not the average, which would let a criterion that is clearly met make
up for one that is not:

| Answers | Reviewer's decision |
|---|---|
| The lowest `p(meets)` ≥ accept threshold | **accepted** |
| Otherwise, the lowest `1 − p(meets)` ≥ reject threshold | **rejected**, with that criterion as the reason |
| Otherwise (nothing strong enough either way) | **unclassified**: left to you |

With both thresholds at 0.9, a study is accepted when every criterion is at
0.90 or more, rejected when one is at 0.10 or less, and left to you in between.
The rules sent to Jev tell it that missing information is not a "no", so a
study is not rejected because its abstract does not mention a criterion. The
comment says what Jev answered for every criterion:

```
Include with AI (run 12, jev-1.13.0): meets every inclusion criterion — meets: I1 0.97, I2 0.95.
Include with AI (run 12, jev-1.13.0): I1 not met (meet 0.06) — meets: I1 0.06, I2 0.90.
Include with AI (run 12, jev-1.13.0): undecided, weakest I2 (meet 0.40) — meets: I1 0.96, I2 0.40.
```

Both phases record the reviewer's decision at the *title and abstract* stage,
so the inclusion decision replaces the "no exclusion criterion" one: the
reviewer's last word on the study is what *Reviewer agreement* compares. The
status follows the decision when the study was unclassified, or accepted or
rejected by this same reviewer (back to unclassified when undecided now);
duplicates and studies classified by someone else keep theirs.

## Reviewers and agreement

Only the main author can screen in someone else's name; any other member (an
agent with its own token, through the API) can only screen as itself. With two
or more reviewers, *Reviewer agreement* gives Cohen's kappa and the
disagreements, and *consolidate* with the **unanimous** rule rejects a study
only when every reviewer rejected it. Deleting an agent in *Manage access*
deletes its decisions and the log of its runs; studies rejected in its name stay
rejected, without an author.

## Before trusting it

Start with one source and read what it rejected (filter *Rejected*; the
*Reviewers* tab shows Jev's probability). If it rejects studies you would keep,
raise the (reject) threshold or add guidance and run again as the same reviewer: its
earlier rejections are screened again and rewritten. A study you mark yourself
is no longer this reviewer's to change. To try another model or guidance
without touching the first results, run it as another reviewer and compare
the two.
