# Codes

The review numbers its **research questions** (RQ1, RQ2… and RQ1.1 for a
sub-question), its **selection criteria** (IC1… for inclusion, EC1… for
exclusion), its **quality assessment questions** (QA1…) and its **data
extraction fields** (EX01…). Write the names without codes: the review gives
them.

- A code comes from the item's place in its list: moving it (the arrows next to
  it) renumbers the list, adding one puts it last, removing one closes the gap.
- A code has as many digits as the longest code of its list: EX01…EX25, RQ1…RQ4.
- The criteria have their own lists, inclusion and exclusion, each on the
  Protocol like the research questions: add, edit, move or remove each one.
- The codes show wherever these items are: the Protocol and the checklists of
  Planning, the study window and the Reviewers tab, the study list's *Criteria*
  column, Quality Assessment, Data Extraction, Data Analysis (charts, PRISMA
  reasons), the report (.docx), the exports and the API.

## Prefixes (Review settings → Codes)

RQ, IC, EC, QA and EX by default. A review written in Portuguese may use QP,
CI, CE…: one to six letters or digits, starting with a letter, each kind its
own.

## Codes typed by hand

*Review settings → Codes* lists the names that start with a code typed by hand
("RQ1: …", "QL1 | …", "EX01 | …") with what they become without it. Tick
them and remove the codes: the History keeps each name as it was. A reference to
a code inside a text ("record it in EX19") is not changed.

## In the API, the CLI and the MCP server

Every research question, criterion, quality question and extraction field has
its `code`; `GET /reviews/{id}/codes` gives the prefixes and the codes typed by
hand, `POST /reviews/{id}/codes/strip` removes them (`keys`: only those),
`PUT /reviews/{id}/criteria/order` reorders a list of criteria, and
`PATCH /reviews/{id}` takes `code_prefixes`.

```
parsifal review update --review alice/my-review --code-prefixes question=QP --code-prefixes inclusion=CI --code-prefixes exclusion=CE
parsifal review codes get --review alice/my-review
parsifal review codes strip --review alice/my-review
parsifal criteria reorder --review alice/my-review --ids 12 --ids 9 --ids 10
```
