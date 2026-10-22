# Running a systematic review with Parsifal (for agents and humans)

Parsifal follows Kitchenham & Charters (2007): **Planning → Conducting → Reporting**.
Every step below is one CLI command (`parsifal ...`) and one MCP tool with the same name.
Start with `parsifal review overview --review <id|author/slug>`: it tells you what exists and
what is still missing.

## 0. Connect

```
export PARSIFAL_URL=http://localhost:8000
export PARSIFAL_TOKEN=pfl_...        # Settings → API tokens, or `manage.py create_api_token`
parsifal me
```

## 1. Planning (the protocol)

1. `review create --title ... --description ...`
2. `review update --review R --objective ... --population ... --intervention ... --comparison ... --outcome ... --context ...`
3. `question create --review R --description "RQ1 ..."` (repeat; `question reorder --ids ...`)
4. `keyword import-picoc --review R` then `keyword update --id K --synonyms a --synonyms b`
   (or `keyword create --description ... --related-to P|I|C|O --synonyms ...`)
5. `search-string generate --review R` → review it → `search-string set --review R --search-string @string.txt`
6. `source defaults` → `source add --review R --source-id N` (default libraries) or
   `source add --review R --name "arXiv" --url arxiv.org` (custom)
7. `criteria create --review R --description ... --criteria-type I` (inclusion) / `E` (exclusion)
8. Quality checklist: `quality question create --review R --description ...`,
   `quality answer suggested --review R` (Yes/Partially/No), `quality set-cutoff --review R --cutoff 1.5`
9. Extraction form: `extraction field create --review R --description "Method" --field-type O --lookup-values "Case study" --lookup-values Survey`
   Field types: B boolean, S string, F float, I integer, D date (MM/DD/YYYY), O select one, M select many.
10. Optional — classification facets (what a mapping study uses instead of detailed extraction):
    `facet create --review R --template research_type` (also research_method, venue_type, study_focus,
    contribution_type) or `facet create --review R --name Topic --multiple --categories A --categories B`.
11. Optional — procedures: `review update --review R --selection-procedure @sel.txt --synthesis-strategy @syn.txt --validity-threats @val.txt`;
    known papers to evaluate the search: `test-set add --review R --title "..." --doi ...`.

## 2. Conducting

1. Adapt the search per source: `source search-string copy-generic --review R --id S`, then
   `source search-string set --review R --id S --search-string @scopus.txt`.
   Run the search in the digital library yourself and export BibTeX, then document it:
   `source document-search --review R --id S --search-type database --searched-at 2026-10-01 --years-from 2015 --years-to 2026 --result-count 120`.
2. Import: `article import --review R --source-id S --bibtex @export.bib`
   (or `article import-file --review R --source-id S --file export.bib`).
3. Duplicates: `article duplicates --review R` → `article resolve-duplicates --review R` (keeps the oldest).
4. Screening: `article list --review R --status U --all` (title, abstract, keywords). Preferred: record your
   own independent decision, `decision record --review R --ids 1 --ids 2 --status A --selection-criteria-id C`
   (`R` to reject with the exclusion criterion as reason; `--comments` for notes); the human reviewer compares
   with `decision agreement` / `decision disagreements` and sets the final status with `decision consolidate`.
   `article set-status ...` changes the consolidated status directly — use it only when asked to.
   Exclude with AI (only when the human asks): `ai-screening run --review R --reviewer-id <your user id>` lets Jev
   reject the studies that clearly meet an exclusion criterion, recording the decisions as you (needs a Jev key:
   `integration jev set --api-key -`; `--statuses` picks the studies sent, default R and U); check them with `ai-screening results --review R --id RUN --outcome excluded`.
   Include with AI (`--phase inclusion`) asks one yes/no question per inclusion criterion: it accepts the studies
   that meet them (every one, or at least one when the protocol's `inclusion_rule` is `any`; a threshold per
   criterion: `--thresholds I1=0.9 --thresholds I2=0.85`) and leaves the rest unclassified for the human; it never
   rejects. Screen with AI (`--phase screen`) asks both in one request: rejected by an exclusion criterion first,
   else accepted by the inclusion criteria, else unclassified. The actions have no order. A run starts from every
   setting of the review's last run of the same action (`ai-screening setup` → `start`); `--defaults` takes
   Parsifal's. `--criteria-ids` picks the criteria sent: leave out what Jev cannot judge from a title and abstract
   (year, language, venue, full text retrieved). What Jev is sent is a template (`start.template`): only change it
   when the human asks, with `--template @request.json`, after checking it with `ai-screening preview`.
   Before a run, `ai-screening impact --review R --reviewer-id U` says whether it would rewrite that reviewer's
   decisions; tell the human first when it would. A run started by mistake is undone with `ai-screening undo
   --review R --id RUN` (check `ai-screening undo-preview` first; only when the human asks): only the latest run can
   be, what still stands of it goes back and the run is deleted, and the run before it becomes the latest.
   `ai-screening rerun --id RUN` starts a new run with RUN's settings.
   `test-set get --review R` tells whether the known papers were found by the search.
   Stars: `article star --review R --article A` marks a study in the review (one star per study, shared with the
   human; not a status); `article list --review R --starred --all` lists them, `article unstar` removes one.
   Full texts: a study's `pdf` field says whether it has one; read it with
   `article pdf download --review R --article A -o paper.pdf`. Attach one (any status, one per study, replaces the
   previous) with `article pdf upload --review R --article A --file paper.pdf`.
5. Quality assessment (accepted articles): `quality assess --review R --article A --question-id Q --answer-id ANS`;
   `quality summary --review R` shows scores against the cutoff. Final selection = accepted AND score > cutoff.
6. Data extraction (final selection): `extraction set --review R --article A --field-id F --value "..."`
   (`--values id --values id` for select-many), then `extraction done --review R --article A`.
   If the review has facets, classify too: `classification set --review R --article A --facet-id F --category-ids C`.
7. Optional — process checklist (Petersen): `checklist set --review R --key search_database --applied --notes "..."`.

## 3. Analysis and reporting

- `analytics selection-by-source --review R`, `analytics final-by-year --review R`
- With facets: `analytics facet-frequencies --review R --facet F`, `analytics facet-matrix --review R --rows F1 --columns F2` (bubble plot)
- `export articles --review R --format csv -o articles.csv`
- `export extraction --review R --format json -o extraction.json`
- `export report --review R -o report.docx` (`--sections name,picoc,research_questions,...`)

## Conventions

- `--review` accepts the numeric id or `author/slug`.
- Text options accept `@path` (file contents) and `-` (stdin).
- Output is JSON when piped or with `--json`; tables on a terminal.
- Exit codes: 0 ok · 1 error · 2 invalid input · 3 authentication/permission · 4 not found · 5 conflict · 6 cannot connect.
- Destructive commands ask for confirmation on a terminal; pass `--yes` in scripts.
