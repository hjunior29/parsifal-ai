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


class ScoreStudiesOut(Schema):
    score: float
    studies: int  # fully assessed studies with this score


class AnswerWeightOut(Schema):
    id: int
    description: str
    weight: float


class AnswerStudiesOut(Schema):
    answer_id: int
    studies: int


class QuestionAnswersOut(Schema):
    id: int
    key: str  # Q1…, in the checklist's order
    description: str
    answers: list[AnswerStudiesOut]  # in the order of ``answers``: the highest weight first
    unanswered: int


class QualityOverviewOut(Schema):
    accepted: int
    questions: int
    assessed: int  # every question answered
    partly: int
    not_assessed: int
    cutoff: float | None  # None without a checklist or a cutoff
    above_cutoff: int | None
    at_most_cutoff: int | None
    max_score: float
    scores: list[ScoreStudiesOut]  # lowest first
    answers: list[AnswerWeightOut]
    by_question: list[QuestionAnswersOut]


class ChoiceOptionOut(Schema):
    id: int | None = None  # the lookup's id; None for true/false
    value: str
    studies: int


class ChoiceFieldOut(Schema):
    id: int
    description: str
    field_type: str  # O (single choice), M (multiple choice) or B (true/false)
    answered: int
    unanswered: int
    options: list[ChoiceOptionOut]  # the most chosen first; true before false


class ExtractionChoicesOut(Schema):
    studies: int  # in the final selection
    done: int  # marked as done
    fields: list[ChoiceFieldOut]
