"""
Backups of one review: everything of it — protocol, sources and search strings, studies and their PDFs, the
reviewers' decisions, AI screening runs, quality assessment, data extraction, classification — in one ``.tar.gz``
(``review.json``, ``files/`` with the PDFs, ``manifest.json`` with checksums).

A backup is kept on the server in the review's list (the newest ``PARSIFAL_REVIEW_BACKUPS_KEEP``), downloaded,
restored over the review (its current content is backed up first) or imported as a new review, here or in another
Parsifal. People are matched by username: someone with no account here gets an inactive one with that username (no
login), so their decisions, agreement and history stay theirs; AI agents come back as agents of the review, without
tokens. Whoever imports a backup as a new review is its main author.
"""

import datetime
import hashlib
import io
import json
import tarfile
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import DateField, DateTimeField
from django.utils import timezone
from django.utils.text import slugify

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.core.models import StoredFile, files_storage
from parsifal.apps.reviews.models import (
    Article,
    ArticleClassification,
    ClassificationCategory,
    ClassificationFacet,
    DataExtraction,
    DataExtractionField,
    DataExtractionLookup,
    Keyword,
    ProcessChecklistItem,
    QualityAnswer,
    QualityAssessment,
    QualityQuestion,
    Question,
    Review,
    ReviewAgent,
    ReviewBackup,
    ReviewTestSetArticle,
    ScreeningResult,
    ScreeningRun,
    SearchSession,
    SelectionCriteria,
    Source,
    StudyDecision,
)
from parsifal.apps.reviews.services._common import get_child
from parsifal.apps.reviews.services.agents import _username_for
from parsifal.apps.reviews.services.reviews import require_owner

FORMAT = 1
KIND = "parsifal-review"
DATA = "review.json"
MANIFEST = "manifest.json"
FILES = "files/"
MAX_MB = 512  # an uploaded backup

# What a review holds, in the order it is created again (each model only points to models before it, or to itself).
CONTENT = (
    ("questions", Question, lambda review: review.research_questions.all()),
    ("criteria", SelectionCriteria, lambda review: review.selectioncriteria_set.all()),
    ("search_sessions", SearchSession, lambda review: review.searchsession_set.all()),
    ("keywords", Keyword, lambda review: review.keywords.all()),
    ("quality_questions", QualityQuestion, lambda review: review.qualityquestion_set.all()),
    ("quality_answers", QualityAnswer, lambda review: review.qualityanswer_set.all()),
    ("fields", DataExtractionField, lambda review: review.dataextractionfield_set.all()),
    ("lookups", DataExtractionLookup, lambda review: DataExtractionLookup.objects.filter(field__review=review)),
    ("facets", ClassificationFacet, lambda review: review.facets.all()),
    ("categories", ClassificationCategory, lambda review: ClassificationCategory.objects.filter(facet__review=review)),
    ("checklist", ProcessChecklistItem, lambda review: review.checklist_items.all()),
    ("files", StoredFile, lambda review: StoredFile.objects.filter(article__review=review)),
    ("articles", Article, lambda review: review.article_set.all()),
    ("test_set", ReviewTestSetArticle, lambda review: review.test_set.all()),
    ("assessments", QualityAssessment, lambda review: QualityAssessment.objects.filter(article__review=review)),
    ("extractions", DataExtraction, lambda review: DataExtraction.objects.filter(article__review=review)),
    (
        "classifications",
        ArticleClassification,
        lambda review: ArticleClassification.objects.filter(article__review=review),
    ),
    ("runs", ScreeningRun, lambda review: review.screening_runs.all()),
    ("results", ScreeningResult, lambda review: ScreeningResult.objects.filter(run__review=review)),
    ("decisions", StudyDecision, lambda review: review.decisions.all()),
)
# Kept as they are when a backup is restored over the review: who it is, and who works on it.
REVIEW_KEPT = ("id", "name", "author_id", "create_date", "last_update", "prisma_not_retrieved_id")


def _value(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _row(obj):
    return {field.attname: _value(getattr(obj, field.attname)) for field in obj._meta.concrete_fields}


def _user_fields(model):
    return [field for field in model._meta.concrete_fields if field.is_relation and field.related_model is User]


def _migrations():
    applied = MigrationRecorder.Migration.objects.order_by("id").values_list("app", "name")
    return {app: name for app, name in applied}


# Backup --------------------------------------------------------------------------------------------------------------


def snapshot(review):
    """Everything of the review, as review.json holds it, and the stored files of its studies' PDFs."""
    data = {
        "format": FORMAT,
        "kind": KIND,
        "created_at": timezone.now().isoformat(timespec="seconds"),
        "migrations": _migrations(),
        "review": _row(review),
        "co_authors": list(review.co_authors.values_list("pk", flat=True)),
        "sources": [_row(source) for source in review.sources.all()],
        "agents": [_row(agent) for agent in review.agents.all()],
    }
    users = {review.author_id, *data["co_authors"], *(agent["user_id"] for agent in data["agents"])}
    for key, model, rows in CONTENT:
        objects = list(rows(review).order_by("pk"))
        data[key] = [_row(obj) for obj in objects]
        for field in _user_fields(model):
            users.update(row[field.attname] for row in data[key] if row[field.attname])
        if model is DataExtraction:
            values = dict.fromkeys((obj.pk for obj in objects), ())
            for extraction_id, lookup_id in DataExtraction.select_values.through.objects.filter(
                dataextraction__article__review=review
            ).values_list("dataextraction_id", "dataextractionlookup_id"):
                values[extraction_id] = (*values[extraction_id], lookup_id)
            for row in data[key]:
                row["select_values"] = list(values[row["id"]])
    agents = {agent["user_id"] for agent in data["agents"]}
    data["users"] = [
        {
            "id": user.pk,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "agent": user.pk in agents,
        }
        for user in User.objects.filter(pk__in=users).order_by("pk")
    ]
    return data


def _archive(review):
    """The review's backup: (the .tar.gz bytes, how many studies it has)."""
    data = snapshot(review)
    storage = files_storage()
    payload = json.dumps(data, ensure_ascii=False).encode()
    manifest = {"format": FORMAT, "kind": KIND, DATA: hashlib.sha256(payload).hexdigest(), "files": {}}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(DATA)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
        for stored in data["files"]:
            with storage.open(stored["key"], "rb") as handle:
                content = handle.read()
            info = tarfile.TarInfo(FILES + stored["key"])
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
            manifest["files"][stored["key"]] = hashlib.sha256(content).hexdigest()
        content = json.dumps(manifest, indent=2).encode()
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue(), len(data["articles"])


def keep():
    return getattr(settings, "PARSIFAL_REVIEW_BACKUPS_KEEP", 10)


def _store(review, content, *, studies, note, actor, filename):
    key = f"backups/reviews/{review.pk}/{uuid.uuid4().hex}.tar.gz"
    stored = StoredFile.objects.create(
        key=files_storage().save(key, ContentFile(content)),
        filename=filename,
        content_type="application/gzip",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        uploaded_by=actor,
    )
    backup = ReviewBackup.objects.create(review=review, file=stored, note=note, studies=studies, created_by=actor)
    newest = keep()
    for old in review.backups.all()[newest:]:
        old.delete()
    return backup


def _filename(review):
    return f"{review.name}-{timezone.localtime().strftime('%Y%m%d-%H%M%S')}.tar.gz"


@transaction.atomic
def create_backup(*, review, actor, note=""):
    """Back up the review into its list on the server (only the main author); the oldest beyond the limit go."""
    require_owner(review, actor)
    content, studies = _archive(review)
    return _store(review, content, studies=studies, note=note, actor=actor, filename=_filename(review))


def list_backups(review, actor):
    require_owner(review, actor)
    return review.backups.select_related("file", "created_by")


def get_backup(review, actor, backup_id):
    require_owner(review, actor)
    return get_child(review.backups.select_related("file"), backup_id, label="Backup")


def delete_backup(*, review, actor, backup_id):
    get_backup(review, actor, backup_id).delete()


def _read(content):
    """The data of a review backup (bytes), once its checksums were checked: (data, archive)."""
    try:
        archive = tarfile.open(fileobj=io.BytesIO(content), mode="r:gz")
        manifest = json.loads(archive.extractfile(MANIFEST).read())
        payload = archive.extractfile(DATA).read()
    except (tarfile.TarError, OSError, KeyError, AttributeError, ValueError):
        raise ValidationError("The file is not a backup of a review.", field="file")
    if manifest.get("kind") != KIND or manifest.get("format") != FORMAT:
        raise ValidationError("The file is not a backup of a review, or comes from another version.", field="file")
    if hashlib.sha256(payload).hexdigest() != manifest.get(DATA):
        raise ValidationError("The backup is damaged.", field="file")
    for key, expected in manifest.get("files", {}).items():
        member = archive.extractfile(FILES + key)
        if member is None or hashlib.sha256(member.read()).hexdigest() != expected:
            raise ValidationError(f"The backup is damaged (file {key}).", field="file")
    data = json.loads(payload)
    current = _migrations().get("reviews", "")
    if data["migrations"].get("reviews", "") > current:
        raise ValidationError(
            "The backup comes from a newer Parsifal: update this one before restoring it.", field="file"
        )
    return data, archive


def upload_backup(*, review, actor, filename, content):
    """Add a backup file (downloaded before, or from another Parsifal) to the review's list, once checked."""
    require_owner(review, actor)
    if len(content) > MAX_MB * 1024 * 1024:
        raise ValidationError(f"The file is larger than {MAX_MB} MB.", field="file")
    data, _archive_file = _read(content)
    name = (filename or "").rsplit("/", 1)[-1][:200] or _filename(review)
    return _store(review, content, studies=len(data["articles"]), note="Uploaded", actor=actor, filename=name)


# Restore and import --------------------------------------------------------------------------------------------------


class _Import:
    """Creates a backup's content in ``review``, keeping a map from the backup's ids to the new ones per model."""

    def __init__(self, review, data, archive, actor):
        self.review, self.data, self.archive, self.actor = review, data, archive, actor
        self.ids = {}

    def map(self, model):
        return self.ids.setdefault(model, {})

    # People
    def people(self):
        """Each user of the backup: the account with that username here, else an inactive one; agents as agents."""
        users = self.map(User)
        agents = {agent["user_id"]: agent for agent in self.data["agents"]}
        own_agents = {agent.user.username: agent.user for agent in self.review.agents.select_related("user")}
        for person in self.data["users"]:
            if person["agent"]:
                user = own_agents.get(person["username"])
                if user is None:
                    agent = agents[person["id"]]
                    free = not User.objects.filter(username__iexact=person["username"]).exists()
                    user = User(
                        username=person["username"] if free else _username_for(agent["name"]),
                        first_name=person["first_name"][:150],
                        is_active=True,
                    )
                    user.set_unusable_password()
                    user.save()
                    self.review.co_authors.add(user)
                    ReviewAgent.objects.create(review=self.review, user=user, name=agent["name"])
            else:
                user = User.objects.filter(username__iexact=person["username"]).first()
                if user is None:
                    user = User(
                        username=person["username"],
                        first_name=person["first_name"],
                        last_name=person["last_name"],
                        is_active=False,
                    )
                    user.set_unusable_password()
                    user.save()
            users[person["id"]] = user.pk
        for old in self.data["co_authors"]:
            new = users.get(old)
            if new and new != self.review.author_id:
                self.review.co_authors.add(new)

    def sources(self):
        sources = self.map(Source)
        for row in self.data["sources"]:
            source = None
            if row["is_default"]:
                source = Source.objects.filter(is_default=True, name=row["name"]).first()
            if source is None:
                source = Source.objects.create(name=row["name"], url=row["url"] or "", is_default=False)
            self.review.sources.add(source)
            sources[row["id"]] = source.pk

    # Rows
    def _fields(self, model, row):
        """The new object's values: the row's, with each reference to another object of the backup mapped."""
        values, later = {}, {}
        for field in model._meta.concrete_fields:
            if field.primary_key or field.attname not in row:
                continue
            value = row[field.attname]
            if field.is_relation and value is not None:
                if field.related_model is Review:
                    value = self.review.pk
                elif field.related_model is model:
                    later[field.attname] = value  # a reference to a row of the same model: once all exist
                    value = None
                else:
                    value = self.map(field.related_model).get(value)
                    if value is None and not field.null:
                        raise ValidationError(f"The backup is incomplete ({model.__name__} {row.get('id')}).")
            elif isinstance(field, DateTimeField) and value:
                value = datetime.datetime.fromisoformat(value)
            elif isinstance(field, DateField) and value:
                value = datetime.date.fromisoformat(value)
            values[field.attname] = value
        return values, later

    def rows(self, key, model):
        mapping, created, pending = self.map(model), [], []
        automatic = [
            field
            for field in model._meta.concrete_fields
            if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False)
        ]
        for row in self.data.get(key, []):
            values, later = self._fields(model, row)
            if model is StoredFile:
                values["key"] = self.file(row)
            if model is ScreeningRun:
                values["parameters"] = self.parameters(values.get("parameters") or {})
            if model is ScreeningResult and values.get("previous_decision"):
                values["previous_decision"] = self.previous_decision(values["previous_decision"])
            obj = model(**values)
            obj.save(force_insert=True)
            mapping[row["id"]] = obj.pk
            created.append((obj, values))
            if later:
                pending.append((obj, later))
            if model is DataExtraction and row.get("select_values"):
                lookups = self.map(DataExtractionLookup)
                obj.select_values.set([lookups[pk] for pk in row["select_values"] if pk in lookups])
        for obj, later in pending:
            for attname, old in later.items():
                setattr(obj, attname, mapping.get(old))
            obj.save(update_fields=[attname.removesuffix("_id") for attname in later])
        if automatic and created:  # saving set them to now: back to the backup's
            for obj, values in created:
                for field in automatic:
                    setattr(obj, field.attname, values.get(field.attname) or getattr(obj, field.attname))
            model.objects.bulk_update(
                [obj for obj, _values in created], [field.name for field in automatic], batch_size=100
            )

    def file(self, row):
        key = f"reviews/{self.review.pk}/{uuid.uuid4().hex}.pdf"
        return files_storage().save(key, ContentFile(self.archive.extractfile(FILES + row["key"]).read()))

    def parameters(self, parameters):
        """An AI screening run's parameters, with the criteria and the source of this review."""
        criteria, sources = self.map(SelectionCriteria), self.map(Source)
        parameters = dict(parameters)
        if parameters.get("criteria"):
            parameters["criteria"] = [
                dict(option, id=criteria.get(option.get("id"))) for option in parameters["criteria"]
            ]
        if parameters.get("skipped_criteria"):
            parameters["skipped_criteria"] = [criteria[pk] for pk in parameters["skipped_criteria"] if pk in criteria]
        if parameters.get("source_id"):
            parameters["source_id"] = sources.get(parameters["source_id"])
        return parameters

    def previous_decision(self, decision):
        decision = dict(decision)
        decision["criteria_id"] = self.map(SelectionCriteria).get(decision.get("criteria_id"))
        decision["run_id"] = self.map(ScreeningRun).get(decision.get("run_id"))
        return decision

    def content(self):
        self.people()
        self.sources()
        for key, model, _rows in CONTENT:
            self.rows(key, model)
        not_retrieved = self.data["review"].get("prisma_not_retrieved_id")
        self.review.prisma_not_retrieved_id = self.map(SelectionCriteria).get(not_retrieved)
        self.review.save(update_fields=["prisma_not_retrieved"])


def _clear(review):
    """Delete the review's content (not the review, its people or its backups) before a restore over it."""
    review.article_set.all().delete()  # their decisions, results, assessments, extractions and PDFs with them
    review.screening_runs.all().delete()
    review.prisma_not_retrieved = None
    review.save(update_fields=["prisma_not_retrieved"])
    for key, model, rows in reversed(CONTENT):
        if model not in (Article, StoredFile, ScreeningResult, ScreeningRun):
            rows(review).delete()
    for source in list(review.sources.all()):
        review.sources.remove(source)
        if not source.is_default:
            source.delete()


@transaction.atomic
def restore_backup(*, review, actor, backup_id):
    """
    Replace the review's content with a backup of its list (only the main author). The current content is backed up
    first, into the list. The review keeps its name, main author, people and agents (their tokens too).
    """
    backup = get_backup(review, actor, backup_id)
    with backup.file.open() as handle:
        content = handle.read()
    data, archive = _read(content)
    create_backup(review=review, actor=actor, note=f"Before restoring {backup.file.filename}")
    _clear(review)
    for field, value in data["review"].items():
        if field not in REVIEW_KEPT and hasattr(review, field):
            setattr(review, field, value)
    review.save()
    _Import(review, data, archive, actor).content()
    return review


@transaction.atomic
def import_review(*, actor, content):
    """A new review from a backup file (bytes), with ``actor`` as its main author."""
    if len(content) > MAX_MB * 1024 * 1024:
        raise ValidationError(f"The file is larger than {MAX_MB} MB.", field="file")
    data, archive = _read(content)
    fields = {
        field: value
        for field, value in data["review"].items()
        if field not in REVIEW_KEPT and field in {f.attname for f in Review._meta.concrete_fields}
    }
    name = slugify(data["review"]["name"]) or "literature-review"
    unique, index = name, 0
    while Review.objects.filter(name=unique, author=actor).exists():
        index += 1
        unique = f"{name}-{index}"
    review = Review.objects.create(name=unique, author=actor, **fields)
    _Import(review, data, archive, actor).content()
    return review
