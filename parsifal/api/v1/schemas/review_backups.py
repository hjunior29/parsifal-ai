from datetime import datetime

from ninja import Schema


class ReviewBackupOut(Schema):
    """A backup of the review kept on the server (everything of it in one .tar.gz)."""

    id: int
    filename: str
    size: int  # bytes
    studies: int
    note: str  # e.g. taken before a restore, or uploaded
    created_by: str | None = None
    created_at: datetime

    @staticmethod
    def resolve_filename(obj):
        return obj.file.filename

    @staticmethod
    def resolve_size(obj):
        return obj.file.size

    @staticmethod
    def resolve_created_by(obj):
        return obj.created_by.username if obj.created_by else None
