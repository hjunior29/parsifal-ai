"""Tabular and document exports. Writers (XLS/CSV/DOCX) consume the rows produced here."""

from parsifal.apps.reviews.models import DataExtraction, DataExtractionField
from parsifal.apps.reviews.reporting.export import export_review_to_docx

ARTICLE_COLUMNS = (
    "bibtex_key",
    "title",
    "author",
    "journal",
    "year",
    "source",
    "pages",
    "volume",
    "abstract",
    "document_type",
    "doi",
    "url",
    "affiliation",
    "author_keywords",
    "keywords",
    "publisher",
    "issn",
    "language",
    "note",
    "selection_criteria",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
    "status",
    "comments",
)

DOCX_SECTIONS = (
    "name",
    "authors",
    "description",
    "picoc",
    "research_questions",
    "keywords_synonyms",
    "search_string",
    "sources",
    "selection_criteria",
    "quality_assessment_checklist",
    "data_extraction_form",
    "classification_scheme",
    "selection_procedure",
    "synthesis_strategy",
    "validity_threats",
    "test_set",
    "source_search_strings",
    "number_imported_studies",
    "search_documentation",
    "quality_assessment",
    "data_extraction",
    "classification_results",
    "data_analysis",
    "process_checklist",
)


def article_row(article):
    return {
        "bibtex_key": article.bibtex_key,
        "title": article.title,
        "author": article.author,
        "journal": article.journal,
        "year": article.year,
        "source": article.source.name if article.source else "",
        "pages": article.pages,
        "volume": article.volume,
        "abstract": article.abstract,
        "document_type": article.document_type,
        "doi": article.doi,
        "url": article.url,
        "affiliation": article.affiliation,
        "author_keywords": article.author_keywords,
        "keywords": article.keywords,
        "publisher": article.publisher,
        "issn": article.issn,
        "language": article.language,
        "note": article.note,
        "selection_criteria": article.selection_criteria.description if article.selection_criteria else "",
        "created_at": article.created_at,
        "updated_at": article.updated_at,
        "created_by": article.created_by.username if article.created_by else "",
        "updated_by": article.updated_by.username if article.updated_by else "",
        "status": article.get_status_display(),
        "comments": article.comments,
    }


def articles_rows(review):
    """(columns, rows) for every article of the review, in the order of the legacy XLS export."""
    articles = review.article_set.select_related("source", "selection_criteria", "created_by", "updated_by")
    return list(ARTICLE_COLUMNS), [article_row(article) for article in articles.order_by("pk")]


def extraction_cell(extraction):
    if extraction is None:
        return ""
    field_type = extraction.field.field_type
    if field_type == DataExtractionField.DATE_FIELD:
        return extraction.get_date_value_as_string()
    if field_type == DataExtractionField.SELECT_ONE_FIELD:
        lookup = extraction._get_select_one_value()
        return lookup.value if lookup else ""
    if field_type == DataExtractionField.SELECT_MANY_FIELD:
        return ", ".join(extraction._get_select_many_value().values_list("value", flat=True))
    return extraction.value or ""


def extraction_rows(review):
    """(columns, rows) — one row per final-selection article, one column per extraction field."""
    fields = list(review.get_data_extraction_fields())
    columns = ["article"] + [field.description for field in fields]
    rows = []
    for article in review.get_final_selection_articles().order_by("title", "pk"):
        extractions = {
            e.field_id: e
            for e in DataExtraction.objects.filter(article=article)
            .select_related("field")
            .prefetch_related("select_values")
        }
        row = {"article": article.title}
        for field in fields:
            row[field.description] = extraction_cell(extractions.get(field.pk))
        rows.append(row)
    return columns, rows


def build_docx(review, sections=None):
    sections = list(DOCX_SECTIONS) if sections is None else [s for s in sections if s in DOCX_SECTIONS]
    return export_review_to_docx(review, sections)
