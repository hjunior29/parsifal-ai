# Exclude, include and screen with AI (Jev)

Study selection by a model, in the name of a reviewer you choose, with three
actions you can run in any order:

- **Exclude with AI**: Jev rejects the studies that clearly meet one of the
  review's **exclusion criteria**. One criterion is enough.
- **Include with AI**: Jev accepts the studies that meet the review's
  **inclusion criteria** — every one of them, or at least one, as the protocol
  says — and leaves the rest unclassified for you. It never rejects.
- **Screen with AI**: both in the same request. A study that clearly meets an
  exclusion criterion is rejected (even when it also meets the inclusion
  criteria); otherwise one that meets the inclusion criteria is accepted; the
  rest are left unclassified for you.

Each study goes to Jev in a request of its own: Jev never reads two studies
together, so its answer about one study does not depend on which others are in
the run or in what order. (Sending several studies in one request is cheaper,
but in Matsui and Takaesu's evaluation of Jev it missed more of the relevant
studies.)

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
   notice and make the screening impossible to reproduce (each answer still
   records the version that gave it). **Test the key** checks that Jev accepts it.
3. Write the exclusion and inclusion criteria in **Planning**, and say there
   whether a study must meet **all the inclusion criteria or at least one**
   (*A study must meet*, under the inclusion criteria). Jev works best in English.

The key is stored encrypted (with a key derived from the instance's `SECRET_KEY`) and is never shown again in
full; if `SECRET_KEY` changes, save the Jev key again. Parsifal's own API tokens are stored as hashes, so not
even Parsifal can read them back. Calls are billed to the key.

## Running it

On **Conducting → Study Selection**, tab *All Sources*, click **Exclude with
AI**, **Include with AI** or **Screen with AI**. The window is the same for the
three and shows what will be sent:

- **Reviewer**: the member of the review the decisions are recorded as. The
  main author can choose anyone in the review (themselves or any AI agent);
  create more reviewers as agents in *Manage access*. One person can thus screen
  as several reviewers (for instance with different models or guidance) and
  compare them in *Reviewer agreement*.
- **Model**: the models Jev lists for your key, asked when the window opens.
- **Review context**: title, objective, research questions and PICOC, taken
  from the review. You can edit them for the run; the review is not changed
  and the run's log keeps what was sent.
- **Extra guidance** (optional): definitions or borderline cases that help apply
  the criteria.
- **Criteria**: from the protocol, each with a checkbox; **only the checked ones
  are sent**. Leave out what Jev cannot judge from a title and abstract — the
  year, the language, the venue, whether the full text was retrieved —: such a
  criterion still takes some of the probability and can reject studies by
  mistake. Exclusion: options `E1`, `E2`… (the protocol's keys) plus `none`.
  Inclusion: `I1`, `I2`…, one yes/no question each.
- **Thresholds** (from 0.5 to 0.99): how sure Jev must be. Exclusion has one,
  to reject (default 0.9). Each inclusion criterion has **its own**, next to it,
  to accept. Screen with AI has both.
- **Studies**: all sources or one, and the **statuses** to send — any mix of
  accepted, rejected, unclassified and duplicated (*All* checks every one).
  Each status shows how many studies it has; nothing is skipped because it was
  screened before.
- **Request to Jev**: what is sent about each study, as JSON you can edit around
  the data (next section). **Preview the request** shows it filled in for the
  first study in scope, with buttons to copy its `state` and `questions` (the
  two fields of Jev's playground).

**The window opens with every setting of the review's last run of the same
action** — reviewer, model, context, guidance, request, criteria, thresholds and
studies —, and says which run they come from. **Restore defaults** puts
Parsifal's back, all at once: the review's context, the default request, every
criterion checked, threshold 0.9, the action's default statuses (exclusion:
rejected and unclassified; inclusion: unclassified and accepted; screen: all
but duplicates), all sources and your default model. Whatever you start with is
what the next run of that action opens with.

**Start screening** sends the studies 64 at a time (up to 32 requests at once,
spaced to stay under Jev's rate limit) and shows the progress until the run
ends, with the time spent and, at that pace, about how long is left; there is
no stop button. **Done** reloads the page.

When the run would rewrite decisions the reviewer already has, or may change the
status of studies the reviewer classified, the window says how many before
anything is sent, and the button becomes **Start anyway**: a second click
starts it. A run that rewrites nothing starts on the first click.

If a run is interrupted — the page was closed, the connection dropped, Jev
refused the key or was unavailable — it keeps the studies it had left. The next
time you open the window it says where the run stopped and offers **Continue**,
which goes on with the settings the run started with. Starting a new run, of
any action, discards the unfinished one.

## Reading the studies in order

The study list has an **AI relevance** column: how likely each study is
relevant, in percent, according to the latest AI run that answered about it —
Exclude with AI, the chance that no exclusion criterion applies
(`1 − p(exclude)`); Include with AI, the chance that it meets the inclusion
criteria (the deciding criterion's `p(meets)`); Screen with AI, the lower of
the two. Click its header to read the most likely first (the studies no run
answered about go last). Jev's probabilities rank studies better than they
measure them, so this order is a good way to read what the thresholds left
unclassified.

## The request to Jev

Each study is sent as one request whose shape is a template: `state` is what
Jev reads; `question` what it is asked (Screen with AI has two: `exclusion` and
`inclusion`). You can reword everything in it — the task, the rules, how each
option or answer is described, where the review context goes, whether the
keywords are sent — except the data, which appear as placeholders that
Parsifal fills in:

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

Each question is asked once, as you word it, and Parsifal reads its answer
directly, so a few things must stay:

- **Exclusion**: `"type": "choice"`, and `criteria` with exactly two entries:
  `"{{key}}"` (repeated for every exclusion criterion sent; its text must
  include `{{criterion}}`) and `"none"`. The question goes as `exclusion`.
- **Inclusion**: `"type": "noul"`, `criteria` with `"true"` and `"false"`, and
  `{{criterion}}` somewhere in the question, which is asked once for every
  inclusion criterion sent, as `inclusion_I1`, `inclusion_I2`…

The default request puts the review and the study (title and abstract) in the
state, and only the task, the rules and the criterion in the questions — what
the questions copied from the preview look like in Jev's playground. Its rules
**keep a study when the title and abstract leave it uncertain**: exclusion
chooses a criterion only when it is clearly indicated, and `none` when it cannot
be told without the full text; inclusion answers yes when the study meets or may
meet the criterion, and no only when it clearly does not. To change that, edit
the request: every run keeps its own in its log (`parameters`), and **Continue**
goes on with it. Edits Parsifal cannot use (invalid JSON, an unknown
placeholder, a missing `none`…) are refused with the reason before anything is
sent.

## From the API, CLI and MCP

The same operations exist outside the web, one to one. Runs use the Jev key of
the account that calls them, so an agent with its own token needs its own key
(`parsifal integration jev set --api-key -` reads it from stdin) and can only
screen as itself. As in the window, **whatever a run leaves out takes the
settings of the review's last run of that action** (`ai-screening setup` shows
them under `start`); `--defaults` takes Parsifal's.

```bash
parsifal integration jev set --api-key - --model jev-1.13.0   # Settings → Integrations
parsifal integration jev test
parsifal ai-screening setup --review R                        # what the window shows (start: the settings a run starts from)
parsifal ai-screening preview --review R --template @request.json   # the request a run would send about the first study in scope
parsifal ai-screening run --review R --reviewer-id U --criteria-ids 3 --criteria-ids 4   # only these criteria
parsifal ai-screening run --review R --reviewer-id U --model jev-1.13.0 --threshold 0.9 --guidance @notes.txt
parsifal ai-screening run --review R --reviewer-id U --statuses U --statuses R --statuses A --source-id 0   # all sources
parsifal ai-screening run --review R --reviewer-id U --phase inclusion --thresholds I1=0.9 --thresholds I2=0.85
parsifal ai-screening run --review R --reviewer-id U --phase screen --threshold 0.9 --thresholds I1=0.85
parsifal ai-screening run --review R --reviewer-id U --defaults   # Parsifal's defaults, not the last run's
parsifal review update --review R --inclusion-rule any        # a study must meet at least one inclusion criterion
parsifal article list --review R --order ai_score             # the most likely relevant first
parsifal ai-screening runs --review R
parsifal ai-screening results --review R --id RUN --outcome excluded
parsifal ai-screening impact --review R --reviewer-id U --phase screen   # what a run would rewrite (asked by start and run too)
parsifal ai-screening rerun --review R --id RUN --threshold 0.7   # a new run with RUN's settings; then `run --run NEW`
parsifal ai-screening undo-preview --review R --id RUN   # what undoing RUN would do
parsifal ai-screening undo --review R --id RUN           # shows that and asks; --yes skips the question
```

`ai-screening run` starts a run and screens until it ends, printing the
progress with the time spent and about how long is left. Ctrl-C, or an interruption from Jev, leaves the run waiting:
`ai-screening run --run RUN` continues it. The step-by-step operations are also
there: `start`, then `step --id RUN` until the run is no longer running. On a
terminal, `start`, `run` and `rerun` first ask when the run would rewrite the
reviewer's decisions, as the window does (`--yes` skips it).
In MCP, `parsifal_ai_screening_run` does the same in one call and says when to
call again with `run_id`.

## What happens to each study: exclusion

For every study Jev receives what the request template sends — by default the
review and the study's **title and abstract** (never authors, venue or
affiliations) — and one multiple-choice question with the criteria sent and
`none`.

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

Every inclusion criterion sent gets its own **yes/no question** ("does the study
meet, or potentially meet, this criterion?"), and Jev answers with the
probability of yes, `p(meets)`. Each criterion has **its own threshold**,
because some are easier to see in an abstract than others. The protocol says
how they combine:

| Rule (Planning) | Accepted when | Otherwise |
|---|---|---|
| all inclusion criteria | every `p(meets)` reaches its criterion's threshold — an average would let a criterion clearly met make up for one that is not | **unclassified** (undecided): left to you |
| at least one inclusion criterion | one `p(meets)` reaches its criterion's threshold | **unclassified** (undecided): left to you |

**Include with AI never rejects.** A study that does not meet the criteria —
whether Jev is unsure or thinks they are not met — stays unclassified, with
Jev's answers in the comment, for you (or Exclude with AI) to decide:

```
Include with AI (run 12, jev-1.13.0): meets every inclusion criterion — meets: I1 0.97, I2 0.95.
Include with AI (run 12, jev-1.13.0): undecided, I1 0.06 below its threshold 0.90 — meets: I1 0.06, I2 0.90.
Include with AI (run 14, jev-1.13.0): meets I2, and one inclusion criterion is enough — meets: I1 0.06, I2 0.90.
```

Every action records the reviewer's decision at the *title and abstract* stage,
so the latest one replaces the earlier ones: the reviewer's last word on the
study is what *Reviewer agreement* compares.

The study's **status** follows the decision only when the study is
unclassified, or was accepted by this same reviewer — the mirror of exclusion:

| Status before the run | Accepted by the run | Undecided |
|---|---|---|
| Unclassified | accepted (the reviewer is its last editor) | stays unclassified |
| Accepted by this reviewer | stays accepted | back to unclassified |
| Accepted by someone else, rejected, duplicated | kept | kept |

As with exclusion, a second reviewer (another model or guidance) screens the
same studies without undoing the first one's acceptances, and *Reviewer
agreement* compares the two.

## What happens to each study: Screen with AI

Jev answers the exclusion question and every inclusion question about the same
request, and the answers are read in that order:

| Answers | Reviewer's decision |
|---|---|
| `1 − p(none)` ≥ the exclusion threshold | **rejected**, with the most probable criterion — even when the inclusion criteria are met |
| otherwise, the inclusion criteria are met (all, or one, as the protocol says) | **accepted** |
| otherwise | **unclassified** (undecided): left to you |

```
Screen with AI (run 20, jev-1.13.0): E2, p(exclude) = 0.95 (inclusion: meets every inclusion criterion — meets: I1 0.97).
Screen with AI (run 20, jev-1.13.0): meets every inclusion criterion — meets: I1 0.93; no exclusion criterion, p(exclude) = 0.04.
```

The study's status follows the decision when the study is unclassified, or was
accepted or rejected by this same reviewer (a study left undecided goes back to
unclassified); duplicates and studies classified by someone else keep theirs.

*Retain with AI*, which asked one retention question per study, was removed:
Screen with AI asks the same criteria, with a reason for each rejection. Its
runs remain in *AI runs*, with their details, but cannot be run again.

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
raise the threshold, leave out a criterion Jev cannot judge, or add guidance,
and run again as the same reviewer: its earlier rejections are screened again
and rewritten (in inclusion, its acceptances). A study you mark yourself is no
longer this reviewer's to change. To try another model or guidance without
touching the first results, run it as another reviewer and compare the two.

## AI runs: what each one did, run again, undo

**AI runs**, next to *Reviewer agreement* on Study Selection, lists the review's
runs, newest first: the action, the reviewer, the model, when it ran and for how
long, the threshold, the statuses sent, the results, and **Still stands** — how
many of the run's decisions are still the reviewer's (the reviewer or a later
run may have replaced them). **Details** shows what was sent (criteria,
context, guidance, request) and Jev's answer for each study, which can be
filtered by answer.

**Run again** opens the run's window with its settings — reviewer, model,
context, guidance, request, criteria, threshold(s) and studies — to change what
you need before starting. The criteria are the protocol's current ones: those
the run left out stay unchecked, one added since is checked; an inclusion
criterion keeps the threshold the run gave it.

**Undo**, on the latest run only, takes back what still stands of it, then
deletes the run with Jev's answers. It first says what it will do, and asks you
to confirm:

- the studies whose status the run changed go back to the status, criterion and
  last editor they had before it, unless someone changed them since: those keep
  the newer status;
- the reviewer's decisions that are still the run's go back to the ones it
  replaced, or are removed when the reviewer had none; decisions replaced since
  stay;
- other reviewers' decisions are never touched.

Runs are undone one at a time, from the newest: once the latest is undone, the
run before it becomes the latest and shows **Undo**, so undoing two runs in a row
goes back to before both. Only the main author can undo a run made in someone
else's name, and no run can be undone while one is being screened. Runs made
before Parsifal kept what came before a run cannot be undone: while the latest
run is one of them, no run shows **Undo**.

## Starting over

To take back the latest runs, **Undo** them in *AI runs* (above), one at a time.

To try another request to Jev from a clean slate, the main author can use
**Review settings → Danger zone → Reset the study selection**. After you
confirm (it cannot be undone):

- every study except duplicates goes back to unclassified, without a criterion;
- the decisions of the reviewers you check are deleted, at every stage (AI
  agents are checked by default, people are not; the others keep theirs);
- a run in progress is discarded.

The log of the AI runs is kept, with the request each one sent, and the next
run starts from the last run's settings (**Restore defaults** brings back
Parsifal's); so are stars, PDFs, quality assessments and extracted data. The
same from the CLI: `parsifal review reset-selection --review R --reviewer-ids 3
--reviewer-ids 4` (it asks for confirmation; `parsifal decision summary --review
R` shows who has decisions).
