"""
Operation registry: one entry per API operation (``operationId`` from the server's OpenAPI document).

The CLI commands and the MCP tools are generated from this list, and a server-side parity test asserts that
every operation exposed by the API is listed here with the same method and path.
"""

from dataclasses import dataclass, field

# Parameter kinds
PATH, QUERY, BODY, FORM, FILE = "path", "query", "body", "form", "file"

# Parameter types (strings; mapped to Python/typer types by the CLI and to JSON schema by the MCP server)
INT, STR, FLOAT, BOOL, TEXT, LIST_INT, LIST_STR = "int", "str", "float", "bool", "text", "list[int]", "list[str]"


@dataclass(frozen=True)
class Param:
    name: str
    type: str = STR
    kind: str = BODY
    required: bool = False
    help: str = ""
    cli: str | None = None  # CLI option name when it differs from ``name`` (snake_case; the CLI uses kebab-case)

    @property
    def option(self):
        return (self.cli or self.name).replace("_", "-")


@dataclass(frozen=True)
class Operation:
    id: str
    method: str
    path: str
    group: tuple
    command: str
    summary: str
    params: tuple = field(default_factory=tuple)
    paginated: bool = False
    download: bool = False
    destructive: bool = False

    @property
    def body_params(self):
        return [p for p in self.params if p.kind in (BODY, FORM, FILE)]

    @property
    def body_mode(self):
        kinds = {p.kind for p in self.params}
        if FORM in kinds or FILE in kinds:
            return "multipart"
        return "json" if BODY in kinds else None

    @property
    def cli_name(self):
        return " ".join((*self.group, self.command))


def P(name, type=STR, kind=PATH, **kw):
    return Param(name, type, kind, **kw)


REVIEW = Param("review_id", INT, PATH, required=True, help="Review id or author/slug.", cli="review")
ARTICLE = Param("article_id", INT, PATH, required=True, help="Article id.", cli="article")


def child_id(name, help_text):
    return Param(name, INT, PATH, required=True, help=help_text, cli="id")


def B(name, type=STR, required=False, help=""):
    return Param(name, type, BODY, required, help)


def Q(name, type=STR, help=""):
    return Param(name, type, QUERY, False, help)


ARTICLE_FIELDS = (
    B("bibtex_key"),
    B("title"),
    B("author"),
    B("journal"),
    B("year"),
    B("pages"),
    B("volume"),
    B("abstract", TEXT),
    B("document_type"),
    B("doi"),
    B("url"),
    B("affiliation"),
    B("author_keywords"),
    B("keywords"),
    B("publisher"),
    B("issn"),
    B("language"),
    B("note"),
    B("comments", TEXT),
)

REVIEW_FIELDS = (
    B("title"),
    B("description", TEXT),
    B("objective", TEXT),
    B("population"),
    B("intervention"),
    B("comparison"),
    B("outcome"),
    B("context"),
    B("quality_assessment_cutoff_score", FLOAT, help="Minimum quality score for the final selection."),
)

OPERATIONS = (
    # Account --------------------------------------------------------------------------------------------------------
    Operation("me", "GET", "/me", (), "me", "Show the authenticated user."),
    Operation("tokens_list", "GET", "/tokens", ("token",), "list", "List your API tokens."),
    Operation(
        "tokens_create",
        "POST",
        "/tokens",
        ("token",),
        "create",
        "Create an API token (key shown once).",
        (B("name", required=True, help="Label for the token."),),
    ),
    Operation(
        "tokens_revoke",
        "DELETE",
        "/tokens/{token_id}",
        ("token",),
        "revoke",
        "Revoke one of your tokens.",
        (child_id("token_id", "Token id."),),
        destructive=True,
    ),
    Operation("users_list", "GET", "/users", ("user",), "list", "List users (administrators only)."),
    Operation(
        "users_create",
        "POST",
        "/users",
        ("user",),
        "create",
        "Create a user account (administrators only).",
        (B("username", required=True), B("email", required=True), B("password"), B("first_name"), B("last_name")),
    ),
    Operation(
        "sources_defaults", "GET", "/sources/defaults", ("source",), "defaults", "List the default digital libraries."
    ),
    # Reviews --------------------------------------------------------------------------------------------------------
    Operation(
        "reviews_list",
        "GET",
        "/reviews",
        ("review",),
        "list",
        "List the reviews you take part in.",
        (
            Q("author", help="Filter by author username."),
            Q("name", help="Filter by slug."),
            Q("q", help="Search title/description."),
        ),
        paginated=True,
    ),
    Operation(
        "reviews_create",
        "POST",
        "/reviews",
        ("review",),
        "create",
        "Create a review.",
        (B("title", required=True), B("description", TEXT)),
    ),
    Operation("reviews_get", "GET", "/reviews/{review_id}", ("review",), "get", "Show a review.", (REVIEW,)),
    Operation(
        "reviews_overview",
        "GET",
        "/reviews/{review_id}/overview",
        ("review",),
        "overview",
        "Counts per protocol section and article status — the best first call for an agent.",
        (REVIEW,),
    ),
    Operation(
        "reviews_update",
        "PATCH",
        "/reviews/{review_id}",
        ("review",),
        "update",
        "Update title, description, objective, PICOC or cutoff score.",
        (REVIEW, *REVIEW_FIELDS),
    ),
    Operation(
        "reviews_delete",
        "DELETE",
        "/reviews/{review_id}",
        ("review",),
        "delete",
        "Delete a review (main author only).",
        (REVIEW,),
        destructive=True,
    ),
    Operation(
        "reviews_rename",
        "PUT",
        "/reviews/{review_id}/name",
        ("review",),
        "rename",
        "Change the review slug (URL).",
        (REVIEW, B("name", required=True, help="New slug.")),
    ),
    Operation(
        "reviews_transfer",
        "POST",
        "/reviews/{review_id}/transfer",
        ("review",),
        "transfer",
        "Transfer ownership to another user; you become a co-author.",
        (REVIEW, B("username", required=True)),
    ),
    Operation(
        "members_list",
        "GET",
        "/reviews/{review_id}/members",
        ("member",),
        "list",
        "List author and co-authors.",
        (REVIEW,),
    ),
    Operation(
        "members_add",
        "POST",
        "/reviews/{review_id}/members",
        ("member",),
        "add",
        "Add an existing user as co-author (main author only).",
        (REVIEW, B("username"), B("email")),
    ),
    Operation(
        "members_remove",
        "DELETE",
        "/reviews/{review_id}/members/{user_id}",
        ("member",),
        "remove",
        "Remove a co-author (main author) or leave the review (yourself).",
        (REVIEW, Param("user_id", INT, PATH, True, "User id.", cli="user_id")),
        destructive=True,
    ),
    # Protocol: research questions ------------------------------------------------------------------------------------
    Operation(
        "questions_list",
        "GET",
        "/reviews/{review_id}/questions",
        ("question",),
        "list",
        "List research questions.",
        (REVIEW,),
    ),
    Operation(
        "questions_create",
        "POST",
        "/reviews/{review_id}/questions",
        ("question",),
        "create",
        "Add a research question.",
        (REVIEW, B("description", TEXT, True), B("parent_id", INT, help="Parent question id (sub-question).")),
    ),
    Operation(
        "questions_update",
        "PATCH",
        "/reviews/{review_id}/questions/{question_id}",
        ("question",),
        "update",
        "Edit a research question.",
        (REVIEW, child_id("question_id", "Question id."), B("description", TEXT, True)),
    ),
    Operation(
        "questions_delete",
        "DELETE",
        "/reviews/{review_id}/questions/{question_id}",
        ("question",),
        "delete",
        "Remove a research question.",
        (REVIEW, child_id("question_id", "Question id.")),
        destructive=True,
    ),
    Operation(
        "questions_reorder",
        "PUT",
        "/reviews/{review_id}/questions/order",
        ("question",),
        "reorder",
        "Reorder research questions.",
        (REVIEW, B("ids", LIST_INT, True, "Question ids in the desired order.")),
    ),
    # Protocol: keywords and search string ----------------------------------------------------------------------------
    Operation(
        "keywords_list",
        "GET",
        "/reviews/{review_id}/keywords",
        ("keyword",),
        "list",
        "List keywords with synonyms.",
        (REVIEW,),
    ),
    Operation(
        "keywords_create",
        "POST",
        "/reviews/{review_id}/keywords",
        ("keyword",),
        "create",
        "Add a keyword.",
        (
            REVIEW,
            B("description", required=True),
            B("related_to", help="P, I, C, O or empty."),
            B("synonyms", LIST_STR, help="Synonyms (repeat the option)."),
        ),
    ),
    Operation(
        "keywords_update",
        "PATCH",
        "/reviews/{review_id}/keywords/{keyword_id}",
        ("keyword",),
        "update",
        "Edit a keyword.",
        (
            REVIEW,
            child_id("keyword_id", "Keyword id."),
            B("description"),
            B("related_to"),
            B("synonyms", LIST_STR, help="Replaces all synonyms."),
        ),
    ),
    Operation(
        "keywords_delete",
        "DELETE",
        "/reviews/{review_id}/keywords/{keyword_id}",
        ("keyword",),
        "delete",
        "Remove a keyword and its synonyms.",
        (REVIEW, child_id("keyword_id", "Keyword id.")),
        destructive=True,
    ),
    Operation(
        "keywords_import_picoc",
        "POST",
        "/reviews/{review_id}/keywords/import-picoc",
        ("keyword",),
        "import-picoc",
        "Create keywords from the comma-separated PICO fields.",
        (REVIEW,),
    ),
    Operation(
        "search_string_get",
        "GET",
        "/reviews/{review_id}/search-string",
        ("search-string",),
        "get",
        "Show the generic search string.",
        (REVIEW,),
    ),
    Operation(
        "search_string_set",
        "PUT",
        "/reviews/{review_id}/search-string",
        ("search-string",),
        "set",
        "Save the generic search string.",
        (REVIEW, B("search_string", TEXT, True)),
    ),
    Operation(
        "search_string_generate",
        "POST",
        "/reviews/{review_id}/search-string/generate",
        ("search-string",),
        "generate",
        "Build the Boolean string from keywords and synonyms (not saved).",
        (REVIEW,),
    ),
    # Protocol: sources ----------------------------------------------------------------------------------------------
    Operation(
        "review_sources_list",
        "GET",
        "/reviews/{review_id}/sources",
        ("source",),
        "list",
        "List the review's sources.",
        (REVIEW,),
    ),
    Operation(
        "review_sources_add",
        "POST",
        "/reviews/{review_id}/sources",
        ("source",),
        "add",
        "Attach a default library (--source-id) or create a custom source (--name/--url).",
        (REVIEW, B("source_id", INT), B("name"), B("url")),
    ),
    Operation(
        "review_sources_update",
        "PATCH",
        "/reviews/{review_id}/sources/{source_id}",
        ("source",),
        "update",
        "Edit a custom source.",
        (REVIEW, child_id("source_id", "Source id."), B("name"), B("url")),
    ),
    Operation(
        "review_sources_remove",
        "DELETE",
        "/reviews/{review_id}/sources/{source_id}",
        ("source",),
        "remove",
        "Detach a source (deletes its imported articles for default libraries).",
        (REVIEW, child_id("source_id", "Source id.")),
        destructive=True,
    ),
    Operation(
        "source_search_strings_list",
        "GET",
        "/reviews/{review_id}/sources/search-strings",
        ("source", "search-string"),
        "list",
        "List per-source search strings.",
        (REVIEW,),
    ),
    Operation(
        "source_search_string_set",
        "PUT",
        "/reviews/{review_id}/sources/{source_id}/search-string",
        ("source", "search-string"),
        "set",
        "Save the search string adapted to a source.",
        (REVIEW, child_id("source_id", "Source id."), B("search_string", TEXT, True)),
    ),
    Operation(
        "source_search_string_copy_generic",
        "POST",
        "/reviews/{review_id}/sources/{source_id}/search-string/copy-generic",
        ("source", "search-string"),
        "copy-generic",
        "Copy the generic search string to a source.",
        (REVIEW, child_id("source_id", "Source id.")),
    ),
    Operation(
        "source_search_string_delete",
        "DELETE",
        "/reviews/{review_id}/sources/{source_id}/search-string",
        ("source", "search-string"),
        "delete",
        "Remove a source's search string.",
        (REVIEW, child_id("source_id", "Source id.")),
        destructive=True,
    ),
    # Protocol: selection criteria -----------------------------------------------------------------------------------
    Operation(
        "criteria_list",
        "GET",
        "/reviews/{review_id}/criteria",
        ("criteria",),
        "list",
        "List inclusion/exclusion criteria.",
        (REVIEW,),
    ),
    Operation(
        "criteria_create",
        "POST",
        "/reviews/{review_id}/criteria",
        ("criteria",),
        "create",
        "Add a criterion.",
        (
            REVIEW,
            B("description", required=True),
            B("criteria_type", required=True, help="I (inclusion) or E (exclusion)."),
        ),
    ),
    Operation(
        "criteria_update",
        "PATCH",
        "/reviews/{review_id}/criteria/{criteria_id}",
        ("criteria",),
        "update",
        "Edit a criterion.",
        (REVIEW, child_id("criteria_id", "Criteria id."), B("description", required=True)),
    ),
    Operation(
        "criteria_delete",
        "DELETE",
        "/reviews/{review_id}/criteria/{criteria_id}",
        ("criteria",),
        "delete",
        "Remove a criterion.",
        (REVIEW, child_id("criteria_id", "Criteria id.")),
        destructive=True,
    ),
    # Quality assessment ---------------------------------------------------------------------------------------------
    Operation(
        "quality_questions_list",
        "GET",
        "/reviews/{review_id}/quality/questions",
        ("quality", "question"),
        "list",
        "List quality checklist questions.",
        (REVIEW,),
    ),
    Operation(
        "quality_questions_create",
        "POST",
        "/reviews/{review_id}/quality/questions",
        ("quality", "question"),
        "create",
        "Add a checklist question.",
        (REVIEW, B("description", required=True)),
    ),
    Operation(
        "quality_questions_update",
        "PATCH",
        "/reviews/{review_id}/quality/questions/{question_id}",
        ("quality", "question"),
        "update",
        "Edit a checklist question.",
        (REVIEW, child_id("question_id", "Question id."), B("description", required=True)),
    ),
    Operation(
        "quality_questions_delete",
        "DELETE",
        "/reviews/{review_id}/quality/questions/{question_id}",
        ("quality", "question"),
        "delete",
        "Remove a checklist question.",
        (REVIEW, child_id("question_id", "Question id.")),
        destructive=True,
    ),
    Operation(
        "quality_questions_reorder",
        "PUT",
        "/reviews/{review_id}/quality/questions/order",
        ("quality", "question"),
        "reorder",
        "Reorder checklist questions.",
        (REVIEW, B("ids", LIST_INT, True)),
    ),
    Operation(
        "quality_answers_list",
        "GET",
        "/reviews/{review_id}/quality/answers",
        ("quality", "answer"),
        "list",
        "List checklist answers and weights.",
        (REVIEW,),
    ),
    Operation(
        "quality_answers_create",
        "POST",
        "/reviews/{review_id}/quality/answers",
        ("quality", "answer"),
        "create",
        "Add an answer with a weight.",
        (REVIEW, B("description", required=True), B("weight", FLOAT, True)),
    ),
    Operation(
        "quality_answers_suggested",
        "POST",
        "/reviews/{review_id}/quality/answers/suggested",
        ("quality", "answer"),
        "suggested",
        "Create Yes (1.0) / Partially (0.5) / No (0.0).",
        (REVIEW,),
    ),
    Operation(
        "quality_answers_update",
        "PATCH",
        "/reviews/{review_id}/quality/answers/{answer_id}",
        ("quality", "answer"),
        "update",
        "Edit an answer.",
        (REVIEW, child_id("answer_id", "Answer id."), B("description"), B("weight", FLOAT)),
    ),
    Operation(
        "quality_answers_delete",
        "DELETE",
        "/reviews/{review_id}/quality/answers/{answer_id}",
        ("quality", "answer"),
        "delete",
        "Remove an answer.",
        (REVIEW, child_id("answer_id", "Answer id.")),
        destructive=True,
    ),
    Operation(
        "quality_max_score",
        "GET",
        "/reviews/{review_id}/quality/max-score",
        ("quality",),
        "max-score",
        "Maximum achievable quality score.",
        (REVIEW,),
    ),
    Operation(
        "quality_set_cutoff",
        "PUT",
        "/reviews/{review_id}/quality/cutoff",
        ("quality",),
        "set-cutoff",
        "Set the cutoff score for the final selection.",
        (REVIEW, B("cutoff", FLOAT, True)),
    ),
    Operation(
        "quality_summary",
        "GET",
        "/reviews/{review_id}/quality/summary",
        ("quality",),
        "summary",
        "Scores of accepted articles and whether they pass the cutoff.",
        (REVIEW,),
    ),
    Operation(
        "article_quality_get",
        "GET",
        "/reviews/{review_id}/articles/{article_id}/quality",
        ("quality",),
        "get",
        "Show an article's assessment.",
        (REVIEW, ARTICLE),
    ),
    Operation(
        "article_quality_assess",
        "PUT",
        "/reviews/{review_id}/articles/{article_id}/quality",
        ("quality",),
        "assess",
        "Answer one checklist question for an article.",
        (REVIEW, ARTICLE, B("question_id", INT, True), B("answer_id", INT, help="Omit to clear the answer.")),
    ),
    # Data extraction ------------------------------------------------------------------------------------------------
    Operation(
        "extraction_fields_list",
        "GET",
        "/reviews/{review_id}/extraction/fields",
        ("extraction", "field"),
        "list",
        "List data extraction fields.",
        (REVIEW,),
    ),
    Operation(
        "extraction_fields_create",
        "POST",
        "/reviews/{review_id}/extraction/fields",
        ("extraction", "field"),
        "create",
        "Add a field (types: B S F I D O M).",
        (
            REVIEW,
            B("description", required=True),
            B("field_type", required=True, help="B, S, F, I, D, O or M."),
            B("lookup_values", LIST_STR, help="Options for select fields (repeat)."),
        ),
    ),
    Operation(
        "extraction_fields_update",
        "PATCH",
        "/reviews/{review_id}/extraction/fields/{field_id}",
        ("extraction", "field"),
        "update",
        "Edit a field.",
        (REVIEW, child_id("field_id", "Field id."), B("description"), B("field_type"), B("lookup_values", LIST_STR)),
    ),
    Operation(
        "extraction_fields_delete",
        "DELETE",
        "/reviews/{review_id}/extraction/fields/{field_id}",
        ("extraction", "field"),
        "delete",
        "Remove a field.",
        (REVIEW, child_id("field_id", "Field id.")),
        destructive=True,
    ),
    Operation(
        "extraction_fields_reorder",
        "PUT",
        "/reviews/{review_id}/extraction/fields/order",
        ("extraction", "field"),
        "reorder",
        "Reorder fields.",
        (REVIEW, B("ids", LIST_INT, True)),
    ),
    Operation(
        "article_extraction_get",
        "GET",
        "/reviews/{review_id}/articles/{article_id}/extraction",
        ("extraction",),
        "get",
        "Show the extracted values of an article.",
        (REVIEW, ARTICLE),
    ),
    Operation(
        "article_extraction_set",
        "PUT",
        "/reviews/{review_id}/articles/{article_id}/extraction",
        ("extraction",),
        "set",
        "Set one field value (--value) or select-many ids (--values).",
        (
            REVIEW,
            ARTICLE,
            B("field_id", INT, True),
            B("value", TEXT),
            B("values", LIST_INT, help="Lookup ids (repeat)."),
        ),
    ),
    Operation(
        "article_extraction_done",
        "PUT",
        "/reviews/{review_id}/articles/{article_id}/extraction/done",
        ("extraction",),
        "done",
        "Mark extraction as done (or undone with --no-done).",
        (REVIEW, ARTICLE, B("done", BOOL)),
    ),
    # Articles -------------------------------------------------------------------------------------------------------
    Operation(
        "articles_list",
        "GET",
        "/reviews/{review_id}/articles",
        ("article",),
        "list",
        "List articles of a review.",
        (
            REVIEW,
            Q("source_id", INT),
            Q("status", help="U, A, R or D."),
            Q("q", help="Title contains."),
            Q("finished_data_extraction", BOOL),
        ),
        paginated=True,
    ),
    Operation(
        "articles_create",
        "POST",
        "/reviews/{review_id}/articles",
        ("article",),
        "create",
        "Add an article manually.",
        (REVIEW, B("source_id", INT, True), *ARTICLE_FIELDS, B("status"), B("selection_criteria_id", INT)),
    ),
    Operation(
        "articles_get",
        "GET",
        "/reviews/{review_id}/articles/{article_id}",
        ("article",),
        "get",
        "Show an article.",
        (REVIEW, Param("article_id", INT, PATH, True, "Article id.", cli="id")),
    ),
    Operation(
        "articles_update",
        "PATCH",
        "/reviews/{review_id}/articles/{article_id}",
        ("article",),
        "update",
        "Edit an article (fields, status, criteria, comments).",
        (
            REVIEW,
            Param("article_id", INT, PATH, True, "Article id.", cli="id"),
            *ARTICLE_FIELDS,
            B("status"),
            B("selection_criteria_id", INT),
        ),
    ),
    Operation(
        "articles_delete",
        "DELETE",
        "/reviews/{review_id}/articles/{article_id}",
        ("article",),
        "delete",
        "Delete an article.",
        (REVIEW, Param("article_id", INT, PATH, True, "Article id.", cli="id")),
        destructive=True,
    ),
    Operation(
        "articles_set_status",
        "POST",
        "/reviews/{review_id}/articles/status",
        ("article",),
        "set-status",
        "Accept/reject/unclassify/mark duplicated several articles.",
        (
            REVIEW,
            B("ids", LIST_INT, True, "Article ids (repeat)."),
            B("status", required=True, help="U, A, R or D."),
            B("selection_criteria_id", INT, help="Reason (criteria id)."),
            B("comments", TEXT),
        ),
    ),
    Operation(
        "articles_import",
        "POST",
        "/reviews/{review_id}/articles/import",
        ("article",),
        "import",
        "Import BibTeX text into a source (use @file.bib or - for stdin).",
        (REVIEW, B("source_id", INT, True), B("bibtex", TEXT, True, "BibTeX content.")),
    ),
    Operation(
        "articles_import_file",
        "POST",
        "/reviews/{review_id}/articles/import/file",
        ("article",),
        "import-file",
        "Upload a .bib file into a source.",
        (REVIEW, Param("source_id", INT, FORM, True), Param("file", STR, FILE, True, "Path to the .bib file.")),
    ),
    Operation(
        "articles_duplicates",
        "GET",
        "/reviews/{review_id}/articles/duplicates",
        ("article",),
        "duplicates",
        "Groups of articles with the same title.",
        (REVIEW,),
    ),
    Operation(
        "articles_resolve_duplicates",
        "POST",
        "/reviews/{review_id}/articles/duplicates/resolve",
        ("article",),
        "resolve-duplicates",
        "Mark duplicates (given ids, or all but the oldest of each group).",
        (REVIEW, B("ids", LIST_INT)),
    ),
    # Analytics and exports ------------------------------------------------------------------------------------------
    Operation(
        "analytics_selection_by_source",
        "GET",
        "/reviews/{review_id}/analytics/selection-by-source",
        ("analytics",),
        "selection-by-source",
        "Imported vs accepted articles per source.",
        (REVIEW,),
    ),
    Operation(
        "analytics_final_by_year",
        "GET",
        "/reviews/{review_id}/analytics/final-by-year",
        ("analytics",),
        "final-by-year",
        "Final selection per publication year.",
        (REVIEW,),
    ),
    Operation(
        "export_articles",
        "GET",
        "/reviews/{review_id}/export/articles.{fmt}",
        ("export",),
        "articles",
        "Download all articles (csv, xlsx or json).",
        (REVIEW, Param("fmt", STR, PATH, True, "csv, xlsx or json.", cli="format")),
        download=True,
    ),
    Operation(
        "export_extraction",
        "GET",
        "/reviews/{review_id}/export/extraction.{fmt}",
        ("export",),
        "extraction",
        "Download the data extraction matrix (csv, xlsx or json).",
        (REVIEW, Param("fmt", STR, PATH, True, "csv, xlsx or json.", cli="format")),
        download=True,
    ),
    Operation(
        "export_report",
        "GET",
        "/reviews/{review_id}/export/report.docx",
        ("export",),
        "report",
        "Download the protocol report (.docx).",
        (REVIEW, Q("sections", help="Comma-separated section keys.")),
        download=True,
    ),
)

BY_ID = {operation.id: operation for operation in OPERATIONS}
