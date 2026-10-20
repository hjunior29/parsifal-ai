# Exclude and include with AI (Jev)

Study selection by a model, in two phases, in the name of a reviewer you choose:

1. **Exclude with AI**: Jev rejects the studies that clearly meet one of the
   review's **exclusion criteria**. One criterion is enough.
2. **Include with AI**: Jev accepts the studies that clearly meet **every**
   **inclusion criterion** and leaves the rest unclassified for you. It never
   rejects: that is the first phase's job.

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
  plus `none` (no criterion applies). Inclusion: `I1`, `I2`…, one yes/no
  question each.
- **Threshold** (default 0.9, from 0.5 to 0.99): how sure Jev must be — to
  reject, in exclusion; to accept, in inclusion.
- **Studies**: all sources or one, and the **statuses** to send — any mix of
  accepted, rejected, unclassified and duplicated (*All* checks every one). The
  default is rejected + unclassified for exclusion, so a second reviewer
  screens the same studies as the first one, including those the first one
  rejected; and unclassified + accepted for inclusion, the studies that are
  still in. Each status shows how many studies it has; nothing is skipped
  because it was screened before.
- **Request to Jev**: what is sent about each study, as JSON you can edit around
  the data (next section). **Preview the request** shows it filled in for the
  first study in scope, with buttons to copy its `state` and `questions` (the
  two fields of Jev's playground).

**Start screening** sends the studies a few at a time and shows the progress
until the run ends; there is no stop button. **Done** reloads the page.

If a run is interrupted — the page was closed, the connection dropped, Jev
refused the key or was unavailable — it keeps the studies it had left. The next
time you open the window it says where the run stopped and offers **Continue**,
which goes on with the settings the run started with (model, context,
thresholds, studies). Starting a new run, of either phase, discards the unfinished one.

## The request to Jev

Each study is sent as one request whose shape is a template: `state` is what
Jev reads, `question` what it is asked. You can reword everything in it — the
task, the rules, how each option or answer is described, where the review
context goes, whether the keywords are sent — except the data, which appear as
placeholders that Parsifal fills in:

| Placeholder | Filled in with |
|---|---|
| `{{review}}` | the review context of the window, as an object (empty fields left out) |
| `{{review.title}}`, `{{review.objective}}`, `{{review.research_questions}}`, `{{review.population}}`… | one context field (the research questions as a list) |
| `{{guidance}}` | the extra guidance |
| `{{study}}` | the study's title, keywords and abstract, as an object |
| `{{study.title}}`, `{{study.keywords}}`, `{{study.abstract}}` | one of them |
| `{{key}}`, `{{criterion}}` | the criterion asked about: `E1`/`I1`… and its description |

A placeholder that is a whole value is replaced by the value itself, and left
out when it is empty; inside a longer text it is replaced by its text. Authors,
venue and affiliations have no placeholder, so they are never sent.

Parsifal still repeats the question, since that is how it combines the answers,
so a few things must stay:

- **Exclusion**: `"type": "choice"`, and `criteria` with exactly two entries:
  `"{{key}}"` (repeated for every exclusion criterion; its text must include
  `{{criterion}}`) and `"none"`. The options are asked in three orders, rotating
  the order of the template.
- **Inclusion**: `"type": "noul"`, `criteria` with `"true"` and `"false"`, and
  `{{criterion}}` somewhere in the question, which is asked once for every
  inclusion criterion, in both orders of the two answers.

A new run starts from the template of the review's last run of the same phase,
so a second reviewer is asked exactly like the first; **Restore the default**
brings back Parsifal's. Each run keeps its template in its log (`parameters`),
and **Continue** goes on with it. Edits Parsifal cannot use (invalid JSON, an
unknown placeholder, a missing `none`…) are refused with the reason before
anything is sent.

## From the API, CLI and MCP

The same operations exist outside the web, one to one. Runs use the Jev key of
the account that calls them, so an agent with its own token needs its own key
(`parsifal integration jev set --api-key -` reads it from stdin) and can only
screen as itself.

```bash
parsifal integration jev set --api-key - --model jev-1.13.0   # Settings → Integrations
parsifal integration jev test
parsifal ai-screening setup --review R                        # what the window shows (reviewers, models, template, studies per status…)
parsifal ai-screening preview --review R --template @request.json   # the request a run would send about the first study in scope
parsifal ai-screening run --review R --reviewer-id U --template @request.json   # a run with an edited request
parsifal ai-screening run --review R --reviewer-id U --model jev-1.13.0 --threshold 0.9 --guidance @notes.txt
parsifal ai-screening run --review R --reviewer-id U --statuses U --statuses R --statuses A   # statuses to send (default R and U)
parsifal ai-screening run --review R --reviewer-id U --phase inclusion --threshold 0.95   # Include with AI (default A and U)
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

For every study Jev receives what the request template sends — by default the
**title, keywords and abstract** (never authors, venue or affiliations). One
multiple-choice question with the criteria and `none` is asked in three option
orders in the same request, because the
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
| The lowest `p(meets)` ≥ threshold | **accepted** |
| Otherwise | **unclassified** (undecided): left to you |

**Include with AI never rejects.** Excluding is the first phase's job; here a
study that does not clearly meet every criterion — whether Jev is unsure or
thinks one is not met — stays unclassified, with Jev's answers in the comment,
for you (or a later step) to decide:

```
Include with AI (run 12, jev-1.13.0): meets every inclusion criterion — meets: I1 0.97, I2 0.95.
Include with AI (run 12, jev-1.13.0): undecided, weakest I1 (meet 0.06) — meets: I1 0.06, I2 0.90.
Include with AI (run 12, jev-1.13.0): undecided, weakest I2 (meet 0.40) — meets: I1 0.96, I2 0.40.
```

Both phases record the reviewer's decision at the *title and abstract* stage,
so the inclusion decision replaces the "no exclusion criterion" one: the
reviewer's last word on the study is what *Reviewer agreement* compares.

The study's **status** follows the decision only when the study is
unclassified, or was accepted by this same reviewer — the mirror of exclusion:

| Status before the run | Accepted by the run | Undecided |
|---|---|---|
| Unclassified | accepted (the reviewer is its last editor) | stays unclassified |
| Accepted by this reviewer | stays accepted | back to unclassified |
| Accepted by someone else, rejected, duplicated | kept | kept |

As with exclusion, a second reviewer (another model or guidance) screens the
same studies — accepted and unclassified, the default — without undoing the
first one's acceptances, and *Reviewer agreement* compares the two.

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
raise the threshold or add guidance and run again as the same reviewer: its
earlier rejections are screened again and rewritten (in inclusion, its
acceptances). A study you mark yourself
is no longer this reviewer's to change. To try another model or guidance
without touching the first results, run it as another reviewer and compare
the two.
