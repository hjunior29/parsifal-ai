from ninja import Schema


class TestSetItemOut(Schema):
    id: int
    title: str
    doi: str
    notes: str
    matched_article_id: int | None = None


class TestSetItemIn(Schema):
    title: str
    doi: str = ""
    notes: str = ""


class TestSetItemUpdateIn(Schema):
    title: str | None = None
    doi: str | None = None
    notes: str | None = None


class TestSetReportOut(Schema):
    total: int
    found: int
    recall: float | None = None
    items: list[TestSetItemOut]


class ChecklistItemOut(Schema):
    key: str
    phase: str  # its group
    label: str
    applied: bool
    notes: str  # in a rapid review, the justification of the concession
    threat: str = ""  # the threat to validity a rapid review's concession brings


class ChecklistOut(Schema):
    catalog: str  # petersen or rapid
    applied: int
    total: int
    ratio: float
    items: list[ChecklistItemOut]


class ChecklistItemIn(Schema):
    applied: bool
    notes: str | None = None
