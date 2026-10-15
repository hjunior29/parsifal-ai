import csv
import io
import json

from django.http import HttpResponse

from ninja import Router
from openpyxl import Workbook

from parsifal.api.deps import get_review
from parsifal.api.v1.schemas.analytics import ByYearOut, SelectionBySourceOut
from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.services import analytics, reports

router = Router(tags=["analytics"])

EXPORT_FORMATS = ("csv", "xlsx", "json")


@router.get(
    "/reviews/{int:review_id}/analytics/selection-by-source",
    response=list[SelectionBySourceOut],
    operation_id="analytics_selection_by_source",
)
def analytics_selection_by_source(request, review_id: int):
    return analytics.selection_by_source(get_review(request, review_id))


@router.get(
    "/reviews/{int:review_id}/analytics/final-by-year",
    response=list[ByYearOut],
    operation_id="analytics_final_by_year",
)
def analytics_final_by_year(request, review_id: int):
    return analytics.final_selection_by_year(get_review(request, review_id))


def _serialise(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _tabular_response(filename, fmt, columns, rows):
    if fmt not in EXPORT_FORMATS:
        raise ValidationError(f"format must be one of {EXPORT_FORMATS}.", field="format")
    if fmt == "json":
        payload = [{column: _serialise(row[column]) for column in columns} for row in rows]
        response = HttpResponse(json.dumps(payload, ensure_ascii=False), content_type="application/json")
    elif fmt == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _serialise(row[column]) for column in columns})
        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    else:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Articles"
        sheet.append(columns)
        for row in rows:
            sheet.append([_cell(row[column]) for column in columns])
        buffer = io.BytesIO()
        workbook.save(buffer)
        response = HttpResponse(
            buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    response["Content-Disposition"] = f'attachment; filename="{filename}.{fmt}"'
    return response


def _cell(value):
    if hasattr(value, "tzinfo") and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


@router.get("/reviews/{int:review_id}/export/articles.{fmt}", operation_id="export_articles")
def export_articles(request, review_id: int, fmt: str):
    """Every article of the review as csv, xlsx or json."""
    columns, rows = reports.articles_rows(get_review(request, review_id))
    return _tabular_response("articles", fmt, columns, rows)


@router.get("/reviews/{int:review_id}/export/extraction.{fmt}", operation_id="export_extraction")
def export_extraction(request, review_id: int, fmt: str):
    """Data extraction matrix (final selection × fields) as csv, xlsx or json."""
    columns, rows = reports.extraction_rows(get_review(request, review_id))
    return _tabular_response("data_extraction", fmt, columns, rows)


@router.get("/reviews/{int:review_id}/export/report.docx", operation_id="export_report")
def export_report(request, review_id: int, sections: str | None = None):
    """Protocol report as .docx; ``sections`` is a comma-separated subset of the section keys (default: all)."""
    review = get_review(request, review_id)
    selected = [s.strip() for s in sections.split(",")] if sections else None
    document = reports.build_docx(review, selected)
    buffer = io.BytesIO()
    document.save(buffer)
    response = HttpResponse(
        buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    response["Content-Disposition"] = f'attachment; filename="{review.name}.docx"'
    return response
