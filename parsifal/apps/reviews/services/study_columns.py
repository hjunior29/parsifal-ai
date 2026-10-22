"""
The columns of the study list on Study Selection: each user chooses which ones it shows and in what order
(``Profile.study_columns``; empty means the default). The checkbox column always comes first.
"""

from parsifal.apps.authentication.models import Profile
from parsifal.apps.core.exceptions import ValidationError

# key, heading, what it shows (the heading's tooltip)
COLUMNS = (
    ("star", "Star", "Starred in this review. Click to sort, starred first"),
    ("bibtex_key", "Bibtex Key", "The study's BibTeX key"),
    ("title", "Title", ""),
    ("author", "Author", ""),
    ("journal", "Journal", "Journal or conference"),
    ("year", "Year", "Publication year"),
    ("source", "Source", "The source the study was imported from"),
    ("doi", "DOI", ""),
    ("document_type", "Document type", ""),
    ("language", "Language", ""),
    ("publisher", "Publisher", ""),
    ("criteria", "Criterion", "The selection criterion of the study's status"),
    (
        "ai_relevance",
        "AI relevance",
        "How likely the study is relevant, according to the latest AI run that screened it (Exclude with AI: the "
        "chance that no exclusion criterion applies; Include with AI: the chance that it meets the inclusion "
        "criteria; Screen with AI: the lower of the two). Empty: no AI run screened it. Click to read the most "
        "likely first.",
    ),
    ("created_by", "Added by", "Who imported or added the study"),
    ("created_at", "Added at", ""),
    ("updated_by", "Last edited by", "Who last changed the study (an edit, a status, an AI run)"),
    ("updated_at", "Last edited at", ""),
    ("status", "Status", ""),
)
KEYS = [key for key, _heading, _help in COLUMNS]
DEFAULT = [
    "star",
    "bibtex_key",
    "title",
    "author",
    "journal",
    "year",
    "created_by",
    "created_at",
    "ai_relevance",
    "status",
]


def clean(columns):
    """The columns chosen, in their order: known keys, each once, at least one."""
    if isinstance(columns, str):
        columns = [columns]
    chosen = []
    for key in columns or []:
        key = str(key).strip()
        if key not in KEYS:
            raise ValidationError(f"Unknown column {key!r}: use {', '.join(KEYS)}.", field="study_columns")
        if key not in chosen:
            chosen.append(key)
    if not chosen:
        raise ValidationError("Choose at least one column.", field="study_columns")
    return chosen


def for_user(user):
    """The columns ``user`` shows, in order (the default when they never chose)."""
    saved = Profile.objects.filter(user=user).values_list("study_columns", flat=True).first() or []
    return [key for key in saved if key in KEYS] or list(DEFAULT)


def save(user, columns):
    """Keep the columns ``user`` chose (see ``clean``); returns them. The default is kept as nothing chosen."""
    columns = clean(columns)
    # The user's own profile: saving the user saves it too (authentication's post_save), so a copy would be undone.
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        profile = Profile.objects.create(user=user)
    profile.study_columns = [] if columns == DEFAULT else columns
    profile.save(update_fields=["study_columns"])
    return columns


def headings(columns):
    """The table's headings for ``columns``: {"key", "label", "help"} each."""
    by_key = {key: (heading, help_text) for key, heading, help_text in COLUMNS}
    return [{"key": key, "label": by_key[key][0], "help": by_key[key][1]} for key in columns]


def choices(columns):
    """Every column for the Columns window: those shown first, in their order, then the others."""
    every = columns + [key for key in KEYS if key not in columns]
    return [dict(heading, shown=heading["key"] in columns) for heading in headings(every)]
