from ninja import Schema


class SelectionBySourceOut(Schema):
    source_id: int
    source: str
    total: int
    accepted: int


class ByYearOut(Schema):
    year: int | None = None
    count: int


class SourceStatusesOut(Schema):
    source_id: int
    source: str
    total: int
    accepted: int
    rejected: int
    unclassified: int
    duplicated: int


class SelectionSummaryOut(Schema):
    total: int  # every study imported
    duplicated: int
    unique: int  # not duplicated
    accepted: int
    rejected: int
    unclassified: int
    final: int  # accepted, and above the quality cutoff when there is one
    duplicated_share: float | None  # of every study imported
    accepted_share: float | None  # of the studies that are not duplicates
    rejected_share: float | None
    unclassified_share: float | None
    by_source: list[SourceStatusesOut]


class CriterionUsageOut(Schema):
    id: int
    key: str  # E1… / I1…, in the protocol's order
    description: str
    studies: int  # rejected studies with this exclusion criterion, or accepted ones with this inclusion criterion


class CriteriaUsageOut(Schema):
    exclusion: list[CriterionUsageOut]  # most used first
    inclusion: list[CriterionUsageOut]
    rejected_without_criterion: int
    accepted_without_criterion: int


class YearStatusesOut(Schema):
    year: int | None = None  # None: no year
    accepted: int
    rejected: int
    unclassified: int
