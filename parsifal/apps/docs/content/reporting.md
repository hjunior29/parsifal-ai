# Reporting: threats to validity

*Reporting* opens on **Threats to Validity**; *Export* downloads the report
(.docx).

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
