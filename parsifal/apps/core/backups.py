"""
Backups of the whole instance: one ``.tar.gz`` with a consistent copy of the SQLite database, every stored file
(the studies' PDFs, from the data directory or the bucket) and a manifest with each file's sha256.

``manage.py backup`` and ``manage.py restore`` use it; the Docker entrypoint takes one before applying migrations.
"""

import hashlib
import io
import json
import re
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.core.models import files_are_local, files_storage

FORMAT = 1
DATABASE = "parsifal.sqlite3"
MANIFEST = "manifest.json"
FILES = "files/"
NAME = re.compile(r"^parsifal-\d{8}-\d{6}\.tar\.gz$")  # the backups --keep prunes (others are left alone)
CHUNK = 1024 * 1024


def backups_dir():
    return Path(settings.PARSIFAL_DATA_DIR) / "backups"


def default_destination():
    return backups_dir() / f"parsifal-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz"


def open_database():
    """A dedicated sqlite3 connection to the configured database (file path or shared-cache memory URI)."""
    if connection.vendor != "sqlite":
        raise ValidationError("Backups are only implemented for SQLite.")
    connection.ensure_connection()  # keeps shared-cache in-memory databases (tests) alive
    name = str(connection.settings_dict["NAME"])
    return sqlite3.connect(name, uri=name.startswith("file:"))


def backup_sqlite(destination):
    """
    Consistent copy of the live SQLite database using the online backup API. A separate read connection is used so
    the copy works while the application is running (WAL mode) and never touches Django's connection.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = open_database()
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return destination


def restore_sqlite(source):
    """Replace the live database contents with ``source``, a SQLite file."""
    origin = sqlite3.connect(str(source))
    try:
        origin.execute("PRAGMA schema_version")  # fails early on a file that is not a SQLite database
    except sqlite3.DatabaseError:
        origin.close()
        raise ValidationError(f"{source} is not a SQLite database.")
    target = open_database()
    try:
        origin.backup(target)
    finally:
        target.close()
        origin.close()


def _stored_names(storage, path=""):
    """Every file of the files storage (the bucket's prefix, or the data directory's files/), recursively."""
    try:
        directories, files = storage.listdir(path)
    except FileNotFoundError:
        return
    for name in files:
        yield f"{path}/{name}" if path else name
    for directory in directories:
        yield from _stored_names(storage, f"{path}/{directory}" if path else directory)


class _Hashing:
    """A read-only file object that computes the sha256 of what is read through it."""

    def __init__(self, handle):
        self.handle = handle
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        data = self.handle.read(size)
        self.digest.update(data)
        return data


def _migrations():
    applied = MigrationRecorder.Migration.objects.order_by("id").values_list("app", "name")
    return {app: name for app, name in applied}


def create_backup(destination=None, *, keep=None):
    """
    Write a backup of the instance to ``destination`` (default: <data dir>/backups/parsifal-<timestamp>.tar.gz):
    the database, every stored file and a manifest. With ``keep``, only the newest ``keep`` timestamped backups of
    that directory remain. Returns (path, number of files).
    """
    destination = Path(destination) if destination else default_destination()
    destination.parent.mkdir(parents=True, exist_ok=True)
    storage = files_storage()
    manifest = {
        "format": FORMAT,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "database": DATABASE,
        "migrations": _migrations(),
        "files_storage": "local" if files_are_local() else "bucket",
        "files": {},
    }
    with tempfile.TemporaryDirectory() as scratch, tarfile.open(destination, "w:gz") as archive:
        copy = backup_sqlite(Path(scratch) / DATABASE)
        archive.add(copy, arcname=DATABASE)
        for name in sorted(_stored_names(storage)):
            info = tarfile.TarInfo(FILES + name)
            info.size = storage.size(name)
            with storage.open(name, "rb") as handle:
                hashing = _Hashing(handle)
                archive.addfile(info, hashing)
            manifest["files"][name] = hashing.digest.hexdigest()
        data = json.dumps(manifest, indent=2).encode()
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    if keep:
        prune(destination.parent, keep)
    return destination, len(manifest["files"])


def prune(directory, keep):
    """Delete the oldest timestamped backups (parsifal-YYYYMMDD-HHMMSS.tar.gz) of ``directory`` beyond ``keep``."""
    backups = sorted(path for path in Path(directory).iterdir() if NAME.match(path.name))
    removed = backups[:-keep] if keep > 0 else []
    for path in removed:
        path.unlink()
    return removed


def _sha256(handle):
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(CHUNK), b""):
        digest.update(chunk)
    return digest.hexdigest()


def read_manifest(archive):
    try:
        manifest = json.loads(archive.extractfile(MANIFEST).read())
    except (KeyError, ValueError):
        raise ValidationError("The archive has no Parsifal manifest: it is not a backup of an instance.")
    if manifest.get("format") != FORMAT:
        raise ValidationError(f"Unknown backup format {manifest.get('format')!r}.")
    return manifest


def check_backup(path):
    """The manifest of the backup at ``path``, once every file was checked against its sha256."""
    try:
        archive = tarfile.open(path, "r:gz")
    except (OSError, tarfile.TarError):
        raise ValidationError(f"{path} is not a backup (.tar.gz) of an instance.")
    with archive:
        manifest = read_manifest(archive)
        for name, expected in manifest["files"].items():
            member = archive.extractfile(FILES + name)
            if member is None or _sha256(member) != expected:
                raise ValidationError(f"The file {name} of the backup is damaged.")
    return manifest


def restore_backup(path):
    """
    Restore the backup at ``path``: first a backup of the current state (returned), then the database and the stored
    files. Files are keyed by a random name and never change, so a file already in the storage is kept; files added
    since the backup stay (the restored database no longer points to them). An old database-only backup
    (``.sqlite3``) restores the database alone. Returns (safety backup, files restored).
    """
    path = Path(path)
    if not path.exists():
        raise ValidationError(f"{path} does not exist.")
    if path.suffix == ".sqlite3":
        safety, _ = create_backup(backups_dir() / f"before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz")
        restore_sqlite(path)
        return safety, 0
    manifest = check_backup(path)
    safety, _ = create_backup(backups_dir() / f"before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz")
    storage = files_storage()
    restored = 0
    with tarfile.open(path, "r:gz") as archive, tempfile.TemporaryDirectory() as scratch:
        database = Path(scratch) / DATABASE
        with archive.extractfile(manifest["database"]) as source, open(database, "wb") as target:
            for chunk in iter(lambda: source.read(CHUNK), b""):
                target.write(chunk)
        restore_sqlite(database)
        for name in manifest["files"]:
            if not storage.exists(name):
                storage.save(name, archive.extractfile(FILES + name))
                restored += 1
    return safety, restored
