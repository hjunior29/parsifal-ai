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
