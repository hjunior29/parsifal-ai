"""Conducting phase: candidate studies (articles) — import, manual entry, selection, duplicates."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field as dataclass_field
from difflib import SequenceMatcher

from django.db import transaction
from django.db.models import BooleanField, ExpressionWrapper, F, Q, Value
from django.db.models.functions import NullIf
from django.utils import timezone
from django.utils.text import slugify

import bibtexparser
from bibtexparser.bparser import BibTexParser

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.services import ai_screening
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


# "@type{key," at the start of a line. Keys may contain spaces in exports (e.g. Scopus "De Pascale2023"), which
# bibtexparser silently drops, so such keys are swapped for a placeholder while parsing and restored afterwards.
ENTRY_HEADER = re.compile(r"^([ \t]*@([A-Za-z]+)[ \t]*[{(][ \t]*)([^,\n]*?)([ \t]*,)", re.MULTILINE)
NON_ENTRY_TYPES = {"comment", "string", "preamble"}


@dataclass
class ParseResult:
    entries: list
    warnings: list = dataclass_field(default_factory=list)
    unreadable: int = 0


def _protect_keys(text):
    """Replace keys that contain whitespace with placeholders; returns the new text and {placeholder: key}."""
    originals = {}

    def replace(match):
        key = match.group(3)
        if match.group(2).lower() in NON_ENTRY_TYPES or not re.search(r"\s", key):
            return match.group(0)
        placeholder = f"pfl-key-{len(originals)}"
        originals[placeholder] = key
        return f"{match.group(1)}{placeholder}{match.group(4)}"

    return ENTRY_HEADER.sub(replace, text), originals


def parse_bibtex_detailed(content):
    """
    Parse BibTeX text/bytes/file. Besides the entries, report what the parser did not hand back: entries whose key
    had spaces are recovered (with their original key), and entries that still cannot be read are counted and named,
    so an import never looks complete when it is not.
    """
    text = _decode(content)
    if not text or not text.strip():
        raise ValidationError("The BibTeX content is empty.", field="bibtex")
    protected, originals = _protect_keys(text)
    try:
        database = bibtexparser.loads(protected, parser=BibTexParser(common_strings=True))
    except Exception as error:
        raise ValidationError(f"Could not parse the BibTeX content: {error}", field="bibtex")
    entries = database.entries
    result = ParseResult(entries=entries)
    for entry in entries:
        if entry.get("ID") in originals:
            original = originals[entry["ID"]]
            entry["ID"] = original
            result.warnings.append(f"{original}: key contains spaces; the entry was kept with its original key.")
    # Cross-check against the entry headers actually present in the text.
    declared = Counter(
        originals.get(match.group(3), match.group(3))
        for match in ENTRY_HEADER.finditer(protected)
        if match.group(2).lower() not in NON_ENTRY_TYPES
    )
    missing = declared - Counter(entry.get("ID") for entry in entries)
    for key, count in missing.items():
        result.unreadable += count
        result.warnings.append(f"{key}: entry could not be read by the BibTeX parser and was not imported.")
    shortfall = len(re.findall(r"^[ \t]*@(?!(?:comment|string|preamble)\b)[A-Za-z]+[ \t]*[{(]", text, re.I | re.M))
    shortfall -= len(entries) + result.unreadable
    if shortfall > 0:
        result.unreadable += shortfall
        result.warnings.append(f"{shortfall} more entries could not be read by the BibTeX parser (no key found).")
    return result


def parse_bibtex(content):
    """Parse BibTeX text/bytes/file into bibtexparser entries, raising ValidationError on malformed input."""
    return parse_bibtex_detailed(content).entries


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
    # Provenance: articles imported for a source are linked to that source's documented search, if any.
    found_via = review.searchsession_set.filter(source=source).first()
    parsed = parse_bibtex_detailed(content)
    result = ImportResult(failed=parsed.unreadable, warnings=list(parsed.warnings))
    for entry in parsed.entries:
        try:
            article = article_from_entry(entry, review=review, source=source, warnings=result.warnings)
            article.created_by = actor
            article.found_via = found_via
            article.save()
        except Exception as error:
            result.failed += 1
            result.warnings.append(f"{entry.get('ID', '<no key>')}: skipped ({error}).")
            continue
        result.imported += 1
        result.articles.append(article)
    return result


def get_article(*, review, article_id):
    return get_child(
        review.article_set.select_related("source", "selection_criteria", "pdf__uploaded_by", "starred_by"),
        article_id,
        label="Article",
    )


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


def clear_articles(*, review, source_id, status=None):
    """
    Delete every article imported into a source (optionally only those with ``status``), e.g. after importing the
    wrong export. The source itself stays. Decisions, assessments and extractions of those articles go with them.
    """
    source = get_child(review.sources, source_id, label="Source")
    queryset = review.article_set.filter(source=source)
    if status is not None:
        queryset = queryset.filter(status=_validate_status(status))
    count = queryset.count()
    queryset.delete()
    return count


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


def set_starred(*, review, article_id, starred, actor=None):
    """
    Star (or unstar) a study in the review: one mark per study, shared by every member, whatever its status. Starring
    a starred study keeps who starred it first. The status and updated_by are left alone.
    """
    article = get_child(review.article_set, article_id, label="Article")
    if starred and article.starred_at is None:
        article.starred_at, article.starred_by = timezone.now(), actor
    elif not starred:
        article.starred_at, article.starred_by = None, None
    article.save(update_fields=["starred_at", "starred_by"])
    return get_article(review=review, article_id=article.pk)


def _blank_last(name):
    # An empty text sorts with the missing ones (last), not before every letter.
    return NullIf(F(name), Value(""))


# The orders of the study list, one per column of Study Selection: the value it sorts by and whether it goes down
# first (the starred, the most likely relevant). A "-" before the name reverses it; studies without the value go last
# either way, and ties go by title.
ORDERS = {
    "title": (F("title"), False),
    "ai_score": (F("ai_relevance"), True),
    "star": (ExpressionWrapper(Q(starred_at__isnull=False), output_field=BooleanField()), True),
    "bibtex_key": (_blank_last("bibtex_key"), False),
    "author": (_blank_last("author"), False),
    "journal": (_blank_last("journal"), False),
    "year": (F("year_int"), False),
    "source": (F("source__name"), False),
    "doi": (_blank_last("doi"), False),
    "document_type": (_blank_last("document_type"), False),
    "language": (_blank_last("language"), False),
    "publisher": (_blank_last("publisher"), False),
    "criteria": (F("selection_criteria__description"), False),
    "created_by": (F("created_by__username"), False),
    "created_at": (F("created_at"), False),
    "updated_by": (F("updated_by__username"), False),
    "updated_at": (F("updated_at"), False),
    "status": (F("status"), False),
}


def ordering(order):
    """The ``order_by`` of the study list for ``order``: a key of ``ORDERS``, reversed by a leading "-"."""
    order = (order or "title").strip()
    reverse = order.startswith("-")
    key = order[1:] if reverse else order
    if key not in ORDERS:
        raise ValidationError(f"order must be one of {', '.join(ORDERS)} (a leading - reverses it).", field="order")
    value, down = ORDERS[key]
    value = value.desc(nulls_last=True) if down != reverse else value.asc(nulls_last=True)
    return value, "title", "pk"


def selected_ids(review, *, ids=None, all_matching=False, source_id=None, status=None, query=None, starred=None):
    """
    The studies an action applies to: ``ids``; or, with ``all_matching``, every study of the review that matches the
    study list's filters (``source_id``, ``status``, ``query``, ``starred``; every study when none is given).
    """
    if all_matching and ids:
        raise ValidationError("Give the studies' ids or all_matching, not both.", field="ids")
    if not all_matching:
        if not ids:
            raise ValidationError(
                "Give the studies' ids, or all_matching to act on every study that matches.", field="ids"
            )
        return list(ids)
    if source_id is not None:
        get_child(review.sources, source_id, label="Source")
    queryset = list_articles(review, source_id=source_id, status=status, query=query, starred=starred)
    return list(queryset.values_list("pk", flat=True))


def list_articles(
    review, *, source_id=None, status=None, query=None, finished_data_extraction=None, starred=None, order=None
):
    """
    The review's studies, filtered, with how likely each is relevant by the latest AI answer (``ai_score``);
    ``order``: a column of the study list (``ORDERS``, by title when none), a leading "-" reverses it.
    """
    queryset = ai_screening.with_relevance(
        review.article_set.select_related("source", "selection_criteria", "pdf__uploaded_by", "starred_by")
    ).order_by(*ordering(order))
    if source_id is not None:
        queryset = queryset.filter(source_id=source_id)
    if status is not None:
        queryset = queryset.filter(status=_validate_status(status))
    if finished_data_extraction is not None:
        queryset = queryset.filter(finished_data_extraction=finished_data_extraction)
    if starred is not None:
        queryset = queryset.filter(starred_at__isnull=not starred)
    if query and query.strip():
        queryset = queryset.filter(search_filter(query))
    return queryset


def search_filter(query):
    """
    Articles whose title, DOI or BibTeX key contains ``query`` (ignoring case); a DOI may be pasted as a doi.org link
    or with a ``doi:`` prefix.
    """
    query = query.strip()
    doi = DOI_PREFIX.sub("", query).strip()
    found = Q(title__icontains=query) | Q(bibtex_key__icontains=query)
    return found | Q(doi__icontains=doi) if doi else found


DASHES = re.compile("[\u2010-\u2015\u2212]")
DOI_PREFIX = re.compile(r"^(?:(?:https?://)?(?:dx\.)?doi\.org/|doi:\s*)", re.I)
# Titles that share a DOI but are less similar than this are flagged for a manual check.
TITLE_SIMILARITY = 0.8


TEX_ACCENTS = {"`": "\u0300", "'": "\u0301", "^": "\u0302", "~": "\u0303", "=": "\u0304", '"': "\u0308", ".": "\u0307"}
TEX_ACCENT = re.compile(r"""\\([`'^~=".])\s*\{?\s*([A-Za-z])\s*\}?""")
TRADEMARKS = re.compile("[\u2122\u00ae\u00a9]")


def untex(text):
    """Plain text from BibTeX markup: ``Moir{\\'e}Mop`` -> ``Moir\u00e9Mop``, ``10.1/a\\_b`` -> ``10.1/a_b``."""
    text = TEX_ACCENT.sub(lambda m: m.group(2) + TEX_ACCENTS[m.group(1)], text or "")
    text = re.sub(r"\\([&%$#_{}])", r"\1", text)
    return unicodedata.normalize("NFC", text.replace("{", "").replace("}", "")).replace("\\", "")


def clean_doi(doi):
    """The bare DOI: no URL/``doi:`` prefix, no BibTeX escapes (``\\_``), no spaces, no trailing dot."""
    doi = DOI_PREFIX.sub("", untex(doi).strip())
    return re.sub(r"\s+", "", doi).rstrip(".,;") or None


def normalize_doi(doi):
    """DOI in a comparable form: the bare DOI (``clean_doi``) in lower case."""
    doi = clean_doi(doi)
    return doi.lower() if doi else None


def title_key(title):
    """
    Slug of the title for comparison: TeX markup resolved, trademark signs dropped and Unicode dashes unified, so
    ``CNN-SSD``/``CNN\u2013SSD`` and ``Moir{\\'e}Mop``/``Moir\u00e9Mop`` match.
    """
    text = unicodedata.normalize("NFKC", TRADEMARKS.sub("", untex(title)))
    return slugify(DASHES.sub("-", text))


@dataclass
class DuplicateGroup:
    articles: list
    match: str  # "doi", "title" or "doi+title"
    needs_review: bool = False
    reason: str = ""


@dataclass
class DuplicateConflict:
    articles: list
    reason: str


def duplicate_report(review):
    """
    Duplicate groups plus conflicts. Articles are grouped when they share a normalized DOI or a title slug (dashes
    unified). Same title with different DOIs is *not* grouped but reported as a conflict; same DOI with clearly
    different titles is grouped but flagged ``needs_review``. Articles are ordered oldest first.
    """
    articles = list(review.article_set.exclude(status=Article.DUPLICATED).order_by("pk"))
    parent = {article.pk: article.pk for article in articles}
    reasons = {}

    def find(pk):
        while parent[pk] != pk:
            parent[pk] = parent[parent[pk]]
            pk = parent[pk]
        return pk

    def union(a, b, kind):
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)
        reasons.setdefault(min(root_a, root_b), set()).add(kind)

    by_doi, by_title = {}, {}
    for article in articles:
        doi = normalize_doi(article.doi)
        if doi:
            by_doi.setdefault(doi, []).append(article)
        key = title_key(article.title)
        if key:
            by_title.setdefault(key, []).append(article)
    for members in by_doi.values():
        for other in members[1:]:
            union(members[0].pk, other.pk, "doi")
    conflicts = []
    for members in by_title.values():
        if len(members) < 2:
            continue
        dois = {normalize_doi(article.doi) for article in members} - {None}
        if len(dois) > 1:
            conflicts.append(
                DuplicateConflict(
                    articles=members,
                    reason="Same title but different DOIs: " + ", ".join(sorted(dois)) + ".",
                )
            )
            continue
        for other in members[1:]:
            union(members[0].pk, other.pk, "title")

    grouped = {}
    for article in articles:
        grouped.setdefault(find(article.pk), []).append(article)
    groups = []
    for root, members in grouped.items():
        if len(members) < 2:
            continue
        kinds = set()
        for pk in {a.pk for a in members}:
            kinds |= reasons.get(pk, set())
        match = "+".join(sorted(kinds)) or "title"
        group = DuplicateGroup(articles=members, match=match)
        keys = [title_key(a.title) for a in members if title_key(a.title)]
        if (
            "doi" in kinds
            and keys
            and any(SequenceMatcher(None, keys[0], key).ratio() < TITLE_SIMILARITY for key in keys)
        ):
            group.needs_review = True
            group.reason = "Same DOI but the titles differ substantially; check before resolving."
        groups.append(group)
    return groups, conflicts


def find_duplicates(review):
    """Groups (lists) of non-duplicated articles identified as the same publication, oldest first."""
    return [group.articles for group in duplicate_report(review)[0]]


@transaction.atomic
def resolve_duplicates(*, review, article_ids=None, actor=None):
    """
    Mark articles as duplicated. With ``article_ids`` only those; without, every duplicate group keeps its
    oldest article and the rest are marked (groups flagged ``needs_review`` are left for a manual decision).
    Returns the articles marked.
    """
    if article_ids is not None:
        articles = get_children(review.article_set, article_ids, label="Article")
    else:
        articles = [a for g in duplicate_report(review)[0] if not g.needs_review for a in g.articles[1:]]
    for article in articles:
        article.status = Article.DUPLICATED
        article.updated_by = actor
    Article.objects.bulk_update(articles, fields=("status", "updated_by"))
    return articles
