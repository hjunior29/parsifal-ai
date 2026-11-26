from datetime import date
from typing import Annotated

from ninja import Schema
from pydantic import BeforeValidator

# A date that "" leaves empty, like null: the CLI's way to clear one (e.g. --searched-at "").
OptionalDate = Annotated[date | None, BeforeValidator(lambda value: None if value == "" else value)]


class Message(Schema):
    detail: str


class OrderIn(Schema):
    ids: list[int]


class CountOut(Schema):
    count: int


class UserOut(Schema):
    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    is_superuser: bool


def resolve_code(obj):
    """The review's code of a research question, criterion, quality question or extraction field (services.codes)."""
    from parsifal.apps.reviews.services import codes  # the schemas are imported before the services' models

    if getattr(obj, "code", None) is None:
        codes.code_of(obj.review, obj)
    return obj.code
