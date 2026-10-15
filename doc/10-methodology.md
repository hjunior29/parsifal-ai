# 10 — Methodology: SLR (Kitchenham & Charters 2007) and SMS (Petersen et al. 2015)

Parsifal was built around the SLR guidelines. This document (1) maps the
guidelines to what the code implements, (2) states what a **systematic
mapping study (SMS)** needs in addition, following Petersen, Vakkalanka &
Kuzniarz (2015), and (3) lists the data-model additions that make both
possible. Both guideline texts are available as structured Markdown and are
indexed in the local code-rag instance as projects `kitchenham-2007` and
`petersen-2015` for quick consultation during development.

Sources: *Guidelines for performing Systematic Literature Reviews in Software
Engineering*, v2.3, EBSE-2007-01 (K); *Guidelines for conducting systematic
mapping studies in software engineering: An update*, IST 64 (2015) 1–18 (P).

## 1. Kitchenham & Charters 2007 — coverage matrix

| K § | Guideline element | Parsifal today | Status |
|-----|-------------------|----------------|--------|
| 5.1 | Need for a review (check existing reviews) | — | Missing (free text could go in `objective`) |
| 5.3 | Research questions; PICOC structure | `Question`, `Review.population…context` | Implemented |
| 5.4 | Protocol: background | `Review.objective` | Implemented (single field) |
| 5.4 | Protocol: search strategy — terms and resources | `Keyword`/synonyms, generic `SearchSession`, `Source` | Implemented |
| 5.4 | Protocol: selection criteria | `SelectionCriteria` I/E | Implemented |
| 5.4 | Protocol: selection **procedures** (number of assessors, disagreement resolution) | — | Missing |
| 5.4 | Protocol: QA checklists and procedures | `QualityQuestion`, `QualityAnswer`, cut-off | Implemented (procedures missing) |
| 5.4 | Protocol: data extraction strategy | `DataExtractionField` | Implemented (strategy/validation text missing) |
| 5.4 | Protocol: synthesis strategy, dissemination, timetable | — | Missing |
| 5.5 | Protocol evaluation (consistency checks) | — | Missing |
| 6.1.1 | Search strategy: trial searches, Boolean strings, per-library adaptation | per-source `SearchSession` | Implemented |
| 6.1.2 | Publication bias / grey literature | — | Missing |
| 6.1.3 | Bibliography management, retrieval | BibTeX import, `library` app | Partial |
| 6.1.4 | **Documenting the search** (Table 2: database, strategy, **date of search**, **years covered**; keep unfiltered results) | only the string | Missing — add `searched_at`, `years`, `result_count`, raw file |
| 6.2.1 | Selection criteria piloted | `SelectionCriteria` | Implemented (no pilot concept) |
| 6.2.2 | Multi-stage selection (title/abstract → full text) | single `status` | Partial (one stage) |
| 6.2.3 | Reliability: ≥2 assessors, **Cohen's Kappa**, test–retest | — (`StudySelection`/`Study` models unused) | Missing |
| 6.3 | Quality assessment; hierarchy of evidence; checklist design; Y/P/N scoring | implemented with weights | Implemented |
| 6.3.3 | QA by ≥2 researchers | `QualityAssessment.user` never set | Missing |
| 6.4.1–2 | Extraction forms: pilot; standard items (reviewer, date, notes) | typed fields, no reviewer/date | Partial |
| 6.4.3 | Extraction by two researchers, check procedure | `DataExtraction.user` never set | Missing |
| 6.4.4 | Multiple publications of same data | duplicate detection by title only | Partial |
| 6.5 | Synthesis: descriptive tables, quantitative (forest plots), qualitative, sensitivity, publication bias | two counts charts | Missing |
| 7.2 | Report structure (Table 9) | DOCX with protocol sections; QA/extraction/analysis headings empty | Partial |
| 7.3 | Evaluating the report (DARE criteria) | — | Missing |
| 8 | Mapping studies as a distinct process | — | Missing → §2 |

Everything marked *Implemented* is what the API must expose first (roadmap
phases 2–3). *Missing* items are candidates for phases 7–8 and for the AI
harness.

## 2. Systematic mapping studies — what changes (Petersen et al. 2015)

### 2.1 Differences that affect the tool (P §2.1, K §8)

| Aspect | SLR | SMS | Tool implication |
|--------|-----|-----|------------------|
| Goal | Aggregate evidence for a specific question | Overview of a topic: trends, gaps, inventory of papers | `Review.review_type`; different report template |
| Research questions | Narrow, often one | Broad, several (frequency, topics, venues, research types…) | Same `Question` model; more of them |
| Search | Must find all relevant studies | Breadth over completeness; large result sets are normal | Same search tooling; stronger bulk screening |
| Quality assessment | Essential (rigor & relevance) | Not required; solution proposals without evaluation are kept to show trends | QA step **optional** per review type; cut-off ignored |
| Data extraction | Detailed, numerical | **Classification** into facets ("categorisation stage", K §8) | New classification-scheme entities |
| Analysis | Narrative / meta-analysis | Totals and frequencies; **bubble plots** of facet × facet | Aggregation endpoints and charts |
| Outcome | Synthesis of findings | Map (inventory + classification) | DOCX/report structure for maps (P §5.3) |

### 2.2 The mapping process (P §5, Table 5 activities)

P §5 consolidates the activities found in published maps. Those relevant to a
tool, with where Parsifal stands:

| Phase (P) | Activity | Parsifal | Needed |
|-----------|----------|----------|--------|
| Need for map (5.1.1) | Motivate need and relevance; define objectives and questions; consult target audience | objective, questions | Fine as is |
| Study identification (5.1.2) — choosing strategy | Database search; **snowballing** (backward/forward); manual search of venues | database only | Record search *type* per `SearchSession` (`database`, `snowballing`, `manual`) and provenance per article (`Article.found_via`) |
| — developing the search | PICO(C); consult experts; iterate; keywords from known papers; standards/thesauri | PICOC → keywords; generic string | Optional "known papers" test set |
| — evaluating the search | **Test set of known papers**; expert evaluation; authors' web pages; test–retest | — | `ReviewTestSetArticle` (DOI/title list) + check "found?" after import |
| — inclusion/exclusion | Objective criteria; add reviewer and resolve disagreements; **decision rules** (e.g. include if any reviewer includes) | single status | Per-reviewer decisions + consolidation rule (§4) |
| Extraction & classification (5.1.3) | Objective criteria; obscure bias info; multiple reviewers; **topic-independent facets**: research type (Wieringa), research method, venue type, study focus, contribution type; **topic-specific** emerging scheme (keywording of abstracts) | typed extraction fields | Classification scheme entities with predefined facet templates; keywording notes |
| Validity (5.1.5, 3.6) | Descriptive, theoretical, generalisability, interpretive validity, repeatability | — | Free-text "validity threats" protocol section |
| Visualisation (5.1.4) | Bubble plots, bar, pie, heat-maps, line, Venn | 2 charts | Facet × facet matrix endpoint; frequency tables |
| Reporting (5.3) | Introduction, related work, method (RQ, search, selection, extraction/QA, classification, validity), results per RQ, discussion, appendix with included and excluded borderline papers | DOCX for SLR | Second DOCX template |
| Evaluate the process (5.4) | Rubric: need (0–3), study identification (0–3), extraction/classification (0–3), validity (0–1); ratio of actions taken | — | Self-assessment checklist stored on the review; report section |

### 2.3 Standard classification facets to ship as templates

- **Research type** (Wieringa et al., used by P): evaluation research,
  validation research, solution proposal, philosophical paper, experience
  report, opinion paper.
- **Contribution type**: process, method, model, tool, metric (P notes it is
  rarely used; offer but do not require).
- **Research method**: case study, experiment, survey, action research,
  grounded theory, … (editable list).
- **Venue type**: journal, conference, workshop, book chapter, thesis, other
  (can be derived from `Article.document_type` / BibTeX entry type).
- **Study focus / context**: academic, industrial, government, open source, …
- **Topic-specific** facets: created by the researcher, categories emerge
  during keywording (P §5.1.3; Petersen 2008 "keywording of abstracts").

## 3. Shared requirements that both guidelines ask for

1. **Who did what, when.** Reviewer identity and date on selection decisions,
   quality assessments and extractions (K 6.4.2, P 5.1.3). The fields exist
   (`QualityAssessment.user`, `DataExtraction.user`) or are trivial to add.
2. **Multiple assessors and agreement.** Independent decisions per reviewer,
   a consolidation step, Cohen's Kappa (K 6.2.3), decision rules (P 5.1.2).
   This is also the mechanism by which an **AI agent can act as one reviewer**
   while a human remains accountable for the final decision.
3. **Search documentation.** Date, years covered, result count and raw export
   per source search (K 6.1.4), plus search type (P 5.1.2).
4. **Multi-stage screening.** At least title/abstract vs. full-text stages
   (K 6.2.2) — representable as `stage` on the per-reviewer decision.
5. **Report completeness.** Both prescribe a report structure; the DOCX
   exporter should have one template per review type and real content for
   QA, extraction/classification and analysis.

## 4. Proposed data-model additions (design only)

Additive changes to `reviews.models`; nothing existing is removed in this
step. Names are proposals to be refined in implementation.

```text
Review
  + review_type        CharField  'slr' | 'mapping'            default 'slr'
  + validity_threats   TextField  (P 5.1.5 / K 7.2 limitations)
  + synthesis_strategy TextField  (K 5.4)                      optional
  + selection_procedure TextField (K 5.4: assessors, rules)    optional

SearchSession
  + search_type   CharField  'database' | 'snowballing' | 'manual' | 'other'
  + searched_at   DateField  (K 6.1.4)
  + years_from / years_to    (K 6.1.4)
  + result_count  Integer
  (repurpose `version` for history, or add SearchSessionRevision)

Article
  + found_via     FK SearchSession null   (provenance)
  + year_int      Integer null            (normalised from `year`)

StudyDecision  (replaces unused StudySelection/Study)
  review, article, user, stage ('title_abstract' | 'full_text'),
  status (U/R/A/D), selection_criteria, comments, decided_at
  unique (article, user, stage)
  → Article.status stays the CONSOLIDATED decision; a service computes
    agreement (Cohen's Kappa) and applies decision rules.

QualityAssessment.user / DataExtraction.user → populated by services;
  add `assessed_at` / `extracted_at`.

ClassificationFacet
  review, name, description, kind ('fixed' | 'emerging'),
  template ('research_type' | 'contribution_type' | 'research_method' |
            'venue_type' | 'study_focus' | null), order
ClassificationCategory
  facet, name, description, order
ArticleClassification
  article, facet, category, user, notes, classified_at
  unique (article, facet, user)      ← multi-reviewer again

ReviewTestSetArticle  (P: "paper test-set")
  review, title, doi, matched_article FK null

ProcessChecklistItem  (P 5.4 rubric; K 7.3 DARE)
  review, key, applied bool, notes
```

Analytics additions: facet × facet counts (bubble plot), facet frequencies,
per-year per-facet; QA score distribution; inter-rater agreement per stage.

Implementation is scheduled in [12-roadmap.md](12-roadmap.md) phases 7 and 8;
the API design in [11-system-design.md](11-system-design.md) reserves the
resource names.

## 5. Using the indexed guidelines

```bash
# semantic search over the guideline text (code-rag at http://localhost:8000)
curl -s 'http://localhost:8000/api/search?project=petersen-2015&top_k=3&q=bubble+plot+facets'
curl -s 'http://localhost:8000/api/search?project=kitchenham-2007&top_k=3&q=documenting+the+search'
# or through MCP tools search_code / find_symbol with project=kitchenham-2007 | petersen-2015
```

Paths returned (e.g. `05/5.1.3-data-extraction-and-classification.md`) are
relative to the respective reference folder.
