from ninja import Schema


class SelectionBySourceOut(Schema):
    source_id: int
    source: str
    total: int
    accepted: int


class ByYearOut(Schema):
    year: int | None = None
    count: int
