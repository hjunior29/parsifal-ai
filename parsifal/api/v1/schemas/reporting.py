from datetime import datetime

from ninja import Schema


class ThreatOut(Schema):
    id: int
    title: str
    category: str  # its type: "Theoretical validity", "Construct validity"... or any other
    description: str
    mitigation: str
    order: int
    created_at: datetime
    updated_at: datetime


class ThreatIn(Schema):
    title: str
    category: str = ""
    description: str = ""
    mitigation: str = ""


class ThreatUpdateIn(Schema):
    title: str | None = None
    category: str | None = None
    description: str | None = None
    mitigation: str | None = None


class ThreatExampleOut(Schema):
    title: str
    category: str


class ThreatTypesOut(Schema):
    types: list[str]
    examples: list[ThreatExampleOut]


class ManuscriptVersionOut(Schema):
    id: int
    number: int
    filename: str
    content_type: str
    size: int
    sha256: str
    notes: str
    created_by: str | None = None  # the username
    created_at: datetime

    @staticmethod
    def resolve_filename(obj):
        return obj.file.filename

    @staticmethod
    def resolve_content_type(obj):
        return obj.file.content_type

    @staticmethod
    def resolve_size(obj):
        return obj.file.size

    @staticmethod
    def resolve_sha256(obj):
        return obj.file.sha256

    @staticmethod
    def resolve_created_by(obj):
        return obj.created_by.username if obj.created_by else None


class ManuscriptOut(Schema):
    id: int
    name: str
    description: str
    order: int
    created_at: datetime
    versions: list[ManuscriptVersionOut]  # the newest first

    @staticmethod
    def resolve_versions(obj):
        return list(obj.versions.all())


class ManuscriptIn(Schema):
    name: str
    description: str = ""


class ManuscriptUpdateIn(Schema):
    name: str | None = None
    description: str | None = None
