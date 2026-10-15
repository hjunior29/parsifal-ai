"""Conducting phase: candidate studies (articles) — import, manual entry, selection, duplicates."""

from dataclasses import dataclass, field as dataclass_field

from django.db import transaction
from django.utils.text import slugify

import bibtexparser
from bibtexparser.bparser import BibTexParser

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.services._common import check_length, get_child, get_children

# Maximum length of every editable Article text field (mirrors the model).
ARTICLE_FIELD_LIMITS = {
    "bibtex_key": 100,
    "title": 1000,
    "author": 1000,
    "journal": 1000,
    "year": 10,
    "pages": 20,
    "volume": 100,
    "abstract": 4000,
    "document_type": 100,
    "doi": 50,
    "url": 500,
    "affiliation": 500,
    "author_keywords": 500,
    "keywords": 500,
    "publisher": 100,
    "issn": 50,
    "language": 50,
    "note": 500,
    "comments": 2000,
}

# BibTeX keys mapped onto Article fields; the first key present wins. bibtexparser lower-cases field names
# and exposes the entry key as "ID" and the entry type as "ENTRYTYPE".
BIBTEX_FIELD_ALIASES = {
    "bibtex_key": ("ID",),
    "title": ("title",),
    "journal": ("journal",),
    "year": ("year",),
    "author": ("author",),
    "abstract": ("abstract",),
    "pages": ("pages",),
    "volume": ("volume",),
    "document_type": ("type", "document_type", "ENTRYTYPE"),
    "doi": ("doi",),
    "url": ("link", "url"),
    "affiliation": ("affiliation",),
    "author_keywords": ("author_keywords",),
    "keywords": ("keywords", "keyword"),
    "publisher": ("publisher",),
    "issn": ("issn",),
    "language": ("language",),
    "note": ("note",),
}

STATUSES = dict(Article.ARTICLE_STATUS)


@dataclass
class ImportResult:
    imported: int = 0
    failed: int = 0
    warnings: list = dataclass_field(default_factory=list)
    articles: list = dataclass_field(default_factory=list)


def _decode(content):
    if isinstance(content, bytes):
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("latin-1")
    if hasattr(content, "read"):
        return _decode(content.read())
    return content


def parse_bibtex(content):
    """Parse BibTeX text/bytes/file into bibtexparser entries, raising ValidationError on malformed input."""
    text = _decode(content)
    if not text or not text.strip():
        raise ValidationError("The BibTeX content is empty.", field="bibtex")
    try:
        database = bibtexparser.loads(text, parser=BibTexParser(common_strings=True))
    except Exception as error:
        raise ValidationError(f"Could not parse the BibTeX content: {error}", field="bibtex")
    return database.entries


def article_from_entry(entry, *, review, source, warnings=None):
    """Build an unsaved Article from one bibtexparser entry, truncating over-long values with a warning."""
    article = Article(review=review, source=source)
    key = entry.get("ID", "<no key>")
    for field_name, aliases in BIBTEX_FIELD_ALIASES.items():
        for alias in aliases:
            if alias in entry:
                value = entry[alias]
                limit = ARTICLE_FIELD_LIMITS[field_name]
                if len(value) > limit:
                    value = value[:limit]
                    if warnings is not None:
                        warnings.append(f"{key}: {field_name} truncated to {limit} characters.")
                setattr(article, field_name, value)
                break
    return article


@transaction.atomic
def import_bibtex(*, review, source_id, content, actor=None):
    source = get_child(review.sources, source_id, label="Source")
    result = ImportResult()
    for entry in parse_bibtex(content):
        try:
            article = article_from_entry(entry, review=review, source=source, warnings=result.warnings)
            article.created_by = actor
            article.save()
        except Exception as error:
            result.failed += 1
            result.warnings.append(f"{entry.get('ID', '<no key>')}: skipped ({error}).")
            continue
        result.imported += 1
        result.articles.append(article)
    return result


def get_article(*, review, article_id):
    return get_child(review.article_set.select_related("source", "selection_criteria"), article_id, label="Article")


def _apply_fields(article, fields):
    unknown = set(fields) - set(ARTICLE_FIELD_LIMITS)
    if unknown:
        raise ValidationError(f"Unknown article fields: {sorted(unknown)}.")
    for name, value in fields.items():
        value = "" if value is None else str(value)
        check_length(value, ARTICLE_FIELD_LIMITS[name], field=name)
        setattr(article, name, value)


def _validate_status(status):
    if status not in STATUSES:
        raise ValidationError(f"status must be one of {sorted(STATUSES)}.", field="status")
    return status


def _get_criteria(review, criteria_id):
    if criteria_id in (None, ""):
        return None
    return get_child(review.selectioncriteria_set, criteria_id, label="Selection criteria")


def create_article(*, review, source_id, actor=None, status=None, selection_criteria_id=None, **fields):
    source = get_child(review.sources, source_id, label="Source")
    article = Article(review=review, source=source, created_by=actor, updated_by=actor)
    _apply_fields(article, fields)
    if status is not None:
        article.status = _validate_status(status)
    article.selection_criteria = _get_criteria(review, selection_criteria_id)
    article.save()
    return article


def update_article(*, review, article_id, actor=None, status=None, selection_criteria_id=..., **fields):
    article = get_child(review.article_set, article_id, label="Article")
    _apply_fields(article, fields)
    if status is not None:
        article.status = _validate_status(status)
    if selection_criteria_id is not ...:
        article.selection_criteria = _get_criteria(review, selection_criteria_id)
    article.updated_by = actor
    article.save()
    return article


def delete_articles(*, review, article_ids):
    articles = get_children(review.article_set, article_ids, label="Article")
    review.article_set.filter(pk__in=[a.pk for a in articles]).delete()
    return len(articles)


def set_status(*, review, article_ids, status, selection_criteria_id=None, comments=None, actor=None):
    """Bulk selection decision; the criteria (reason) and comments are optional and applied to every article."""
    _validate_status(status)
    criteria = _get_criteria(review, selection_criteria_id)
    articles = get_children(review.article_set, article_ids, label="Article")
    if comments is not None:
        check_length(comments, ARTICLE_FIELD_LIMITS["comments"], field="comments")
    updates = {"status": status, "updated_by": actor}
    if selection_criteria_id is not None:
        updates["selection_criteria"] = criteria
    if comments is not None:
        updates["comments"] = comments
    review.article_set.filter(pk__in=[a.pk for a in articles]).update(**updates)
    return len(articles)


def list_articles(review, *, source_id=None, status=None, query=None, finished_data_extraction=None):
    queryset = review.article_set.select_related("source", "selection_criteria").order_by("title", "pk")
    if source_id is not None:
        queryset = queryset.filter(source_id=source_id)
    if status is not None:
        queryset = queryset.filter(status=_validate_status(status))
    if finished_data_extraction is not None:
        queryset = queryset.filter(finished_data_extraction=finished_data_extraction)
    if query:
        queryset = queryset.filter(title__icontains=query)
    return queryset


def find_duplicates(review):
    """Groups (lists) of non-duplicated articles sharing the same slugified title, oldest first."""
    groups = {}
    for article in review.article_set.exclude(status=Article.DUPLICATED).order_by("pk"):
        groups.setdefault(slugify(article.title or ""), []).append(article)
    return [articles for articles in groups.values() if len(articles) > 1]


@transaction.atomic
def resolve_duplicates(*, review, article_ids=None, actor=None):
    """
    Mark articles as duplicated. With ``article_ids`` only those; without, every duplicate group keeps its
    oldest article and the rest are marked. Returns the articles marked.
    """
    if article_ids is not None:
        articles = get_children(review.article_set, article_ids, label="Article")
    else:
        articles = [article for group in find_duplicates(review) for article in group[1:]]
    for article in articles:
        article.status = Article.DUPLICATED
        article.updated_by = actor
    Article.objects.bulk_update(articles, fields=("status", "updated_by"))
    return articles
