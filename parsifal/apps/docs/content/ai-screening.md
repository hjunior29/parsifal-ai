# Exclude with AI (Jev)

**Exclude with AI** is the first phase of study selection done by a model: Jev
reads each unclassified study and rejects the ones that clearly meet one of the
review's **exclusion criteria**. Every other study stays unclassified, for the
next phase with the inclusion criteria.

[Jev](https://docs.typesafe.ai/models) is TypeSafe's decision model: it does not
write text, it returns the probability of each allowed answer.

## Setting it up

1. Create an API key in your TypeSafe account.
2. In **Settings → Integrations**, paste the key and keep the model pinned to a
   version (default `jev-1.13.0`). Aliases such as `jev-latest` change without
   notice and make the screening impossible to reproduce. **Test the key**
   checks that Jev accepts it.
3. Write the exclusion criteria in **Planning**. Jev works best in English.

The key is stored in this instance's database and is never shown again in full.
Calls are billed to it.

## Running it

On **Conducting → Study Selection**, tab *All Sources*, click **Exclude with
AI**. The window shows what will be sent:

- **Review context**: title, objective, research questions and PICOC, taken
  from the review. You can edit them for this run; the review is not changed
  and the run's log keeps what was sent.
- **Extra guidance** (optional): definitions or borderline cases that help apply
  the criteria.
- **Exclusion criteria**: from the protocol, read-only, as options `E1`, `E2`…
  plus `none` ("no criterion clearly applies, or there is not enough
  information").
- **Threshold** (default 0.9, from 0.5 to 0.99).
- **Studies**: all sources or one, and whether to screen again the studies Jev
  has already evaluated.

**Start screening** sends the studies a few at a time and shows the progress.
**Stop** ends the run after the current batch. **Done** reloads the page.

## From the API, CLI and MCP

The same operations exist outside the web, one to one. Runs use the Jev key of
the account that calls them, so an agent with its own token needs its own key
(`parsifal integration jev set --api-key -` reads it from stdin).

```bash
parsifal integration jev set --api-key - --model jev-1.13.0   # Settings → Integrations
parsifal integration jev test
parsifal ai-screening setup --review R                        # what the window shows
parsifal ai-screening run --review R --threshold 0.9 --source-id S --guidance @notes.txt
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

- `1 − p(none)` ≥ threshold: the study is **rejected**, with the most probable
  criterion as the reason. The review's **Jev** agent is the author: it appears
  in *Manage access*, in the article's *Reviewers* tab (with the probability in
  the comment) and as the study's last editor.
- otherwise: the study **stays unclassified**. Only the run's log records that
  Jev passed it.

Only unclassified studies are sent; accepted, rejected and duplicated ones are
never touched, and a study someone classifies while the run is going keeps that
status. Studies that failed (for example, with no title or abstract) stay
unclassified and are sent again next time.

## The Jev agent

The first run creates a **Jev** agent in the review: a co-author with an account
of its own and no API token (Parsifal calls Jev for it). Its rejections count as
one reviewer's decisions in *Reviewer agreement*. Deleting it in *Manage
access* deletes its decisions and the log of its runs; the studies it rejected
stay rejected, without an author.

## Before trusting it

Start with one source and read what it rejected (filter *Rejected*; the
*Reviewers* tab shows Jev's probability). If it rejects studies you would keep,
mark them back as unclassified (they are not sent again unless you ask) and
raise the threshold or add guidance before the next run.
