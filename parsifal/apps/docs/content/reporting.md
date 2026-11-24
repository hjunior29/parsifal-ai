# Reporting: threats to validity and manuscripts

*Reporting* has three tabs: **Threats to Validity**, where it opens;
**Manuscripts**, the texts written from the review and their versions; and
*Export*, which downloads the report (.docx).

## Threats to Validity

A review reports what may limit the validity of its results, and what was done
to reduce it: Kitchenham & Charters (2007, §7) ask the report to discuss the
strengths and weaknesses of the review; Petersen et al. (2015, §3.6 and §5.1.5)
discuss the threats of a mapping study by type.

Each threat has:

| Field | What it says |
|-------|--------------|
| Name | The threat in a few words: *Selection by a single researcher* |
| Type | Free text. Suggested: the types of Petersen et al. (2015) — descriptive validity, theoretical validity, generalizability, interpretive validity, repeatability — and those of Wohlin et al. (2012) — construct, internal, external and conclusion validity. Any other is accepted, and so is none. |
| Description | What may limit the validity of the results, and why |
| Mitigation | What was done to reduce it |

The page lists the threats by type. *Add a threat* opens the form, with the
common threats of Petersen et al. (2015, §5.1.5) to start from: a click fills
the name and the type. Each threat is edited in place or removed.

Adding, changing or removing a threat is recorded in the
[History](/docs/history/), in the *Reporting* area; it is never an amendment to
the protocol. Review backups carry the threats, and the report has a
*Threats to Validity* section (Export → Reporting).

```
parsifal threat types
parsifal threat create --review alice/my-review --title "Selection by one researcher" \
  --category "Theoretical validity" --description "Studies may have been missed." \
  --mitigation "A test set of known studies."
parsifal threat list --review alice/my-review
```

API: `GET /api/v1/threats/types`, `GET|POST /api/v1/reviews/{id}/threats`,
`PATCH|DELETE /api/v1/reviews/{id}/threats/{threat_id}`. The MCP server has the
same as `parsifal_threat_*` tools.

## Manuscripts

The texts written from the review: the paper, a short or an extended version
of it, the same paper in another template, a report for practitioners. Each
**manuscript** has a name of your choice (*Full paper*, *Extended abstract*,
*Paper in the SBC template*…; a few are suggested, none is fixed) and a
description of what sets it apart: its template, venue or length.

Each file uploaded to a manuscript is a **new version** (v1, v2, …), with a
note on what changed; no upload replaces an earlier one. A version may be:

| File | Here |
|------|------|
| PDF | *Read* opens it in a viewer on the page (or in a new tab); *Download* saves it |
| Word (.docx), OpenDocument (.odt), LaTeX (.tex), ZIP (a LaTeX project) | *Download* |

The content must be what the name says (a `.pdf` must be a PDF), up to
`PARSIFAL_PDF_MAX_MB` (50 MB by default). A version can be deleted, with its
file; the others keep their numbers, and a number is never given twice.
Deleting a manuscript deletes all its versions.

Every manuscript added, renamed or deleted and every version uploaded or
deleted is recorded in the [History](/docs/history/), in the *Reporting* area.
Review backups carry the manuscripts and their files.

```
parsifal manuscript create --review alice/my-review --name "Full paper" --description "SBES template"
parsifal manuscript version upload --review alice/my-review --manuscript 3 --file paper.pdf --notes "After the reviews"
parsifal manuscript list --review alice/my-review
parsifal manuscript version download --review alice/my-review --manuscript 3 --id 7 -o paper.pdf
```

API: `GET|POST /api/v1/reviews/{id}/manuscripts`,
`PATCH|DELETE /api/v1/reviews/{id}/manuscripts/{manuscript_id}`,
`POST …/manuscripts/{manuscript_id}/versions` (multipart `file`, `notes`),
`GET …/versions/{version_id}/file`, `DELETE …/versions/{version_id}`. The MCP
server has the same as `parsifal_manuscript_*` tools.

