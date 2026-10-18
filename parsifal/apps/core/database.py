from django.db.backends.signals import connection_created

# Pragmas applied to every SQLite connection. WAL lets readers and the single writer coexist (gunicorn
# workers + CLI), busy_timeout waits instead of failing when the writer lock is held, and foreign_keys
# makes SQLite enforce the constraints declared by the models.
SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=30000",
    "PRAGMA foreign_keys=ON",
)


def configure_sqlite(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        for pragma in SQLITE_PRAGMAS:
            cursor.execute(pragma)


def register():
    connection_created.connect(configure_sqlite, dispatch_uid="parsifal.core.configure_sqlite")
