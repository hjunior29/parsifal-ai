# Exclude with AI (Jev)

**Exclude with AI** is the first phase of study selection done by a model: Jev
reads each study and rejects the ones that clearly meet one of the review's
**exclusion criteria**, in the name of a reviewer you choose. Every other study
stays unclassified, for the next phase with the inclusion criteria.

[Jev](https://docs.typesafe.ai/models) is TypeSafe's decision model: it does not
write text, it returns the probability of each allowed answer.

## Setting it up

1. Create an API key in your TypeSafe account.
2. In **Settings → Integrations**, paste the key and save. The page then asks Jev
   for the models your key can use (every time it loads) and you pick the
   **default model**, which is saved; each run can still use another one. Prefer
   a pinned version (`jev-1.13.0`): aliases such as `jev-latest` change without
   notice and make the screening impossible to reproduce. **Test the key**
   checks that Jev accepts it.
3. Write the exclusion criteria in **Planning**. Jev works best in English.

The key is stored encrypted (with a key derived from the instance's `SECRET_KEY`) and is never shown again in
full; if `SECRET_KEY` changes, save the Jev key again. Parsifal's own API tokens are stored as hashes, so not
even Parsifal can read them back. Calls are billed to the key.

## Running it

On **Conducting → Study Selection**, tab *All Sources*, click **Exclude with
AI**. The window shows what will be sent:

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
- **Exclusion criteria**: from the protocol, read-only, as options `E1`, `E2`…
  plus `none` ("no criterion clearly applies, or there is not enough
  information").
- **Threshold** (default 0.9, from 0.5 to 0.99).
- **Studies**: all sources or one. A run sends the unclassified studies plus
  those this reviewer rejected in an earlier run; nothing is skipped because it
  was screened before.

**Start screening** sends the studies a few at a time and shows the progress.
**Stop** ends the run after the current batch. **Done** reloads the page.

## From the API, CLI and MCP

The same operations exist outside the web, one to one. Runs use the Jev key of
the account that calls them, so an agent with its own token needs its own key
(`parsifal integration jev set --api-key -` reads it from stdin) and can only
screen as itself.

```bash
parsifal integration jev set --api-key - --model jev-1.13.0   # Settings → Integrations
parsifal integration jev test
parsifal ai-screening setup --review R                        # what the window shows (reviewers, models…)
parsifal ai-screening run --review R --reviewer-id U --model jev-1.13.0 --threshold 0.9 --guidance @notes.txt
parsifal ai-screening runs --review R
parsifal ai-screening results --review R --id RUN --outcome excluded
```

`ai-screening run` starts a run and screens until it ends, printing the
progress (Ctrl-C cancels the run). The step-by-step operations are also there:
`start`, then `step --id RUN` until the run is no longer running, or `cancel`.
In MCP, `parsifal_ai_screening_run` does the same in one call and says when to
call again with `run_id`. Context fields you leave out take the review's
values.

## What happens to each study

For every study Jev receives the **title, keywords and abstract only** (never
authors, venue or affiliations). One multiple-choice question with the criteria
and `none` is asked in three option orders in the same request, because the
model tends to favour the first option when unsure; the answers are averaged.

Probabilities of the options add up to 1, so the probability that *some*
criterion applies is `1 − p(none)`, even when two criteria split it. Then:

- `1 − p(none)` ≥ threshold: the reviewer's decision is **rejected**, with the
  most probable criterion as the reason, and the study is rejected with it (the
  reviewer is its last editor).
- otherwise: the reviewer's decision is **unclassified** ("no exclusion
  criterion") and the study stays unclassified — or goes back to unclassified
  if this reviewer had rejected it in an earlier run.

Every study screened gets the reviewer's decision, visible in the article's
*Reviewers* tab with the probability in the comment. Recording the "no
criterion" decisions too is what lets two reviewers be compared: their
agreement counts the studies both kept, not only those both rejected. Running
again as the same reviewer rewrites its decisions.

Studies accepted, marked as duplicates or rejected by anyone else are never sent
nor changed, and a study someone classifies while the run is going keeps that
status. Studies that failed (for example, with no title or abstract) keep the
reviewer's previous decision.

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
earlier rejections are screened again and rewritten. A study you mark yourself
is no longer this reviewer's to change.
