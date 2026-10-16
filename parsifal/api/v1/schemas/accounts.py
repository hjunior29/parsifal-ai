from datetime import datetime

from ninja import Schema

from parsifal.api.v1.schemas.common import UserOut


class MeOut(UserOut):
    active_tokens: int


class MeUpdateIn(Schema):
    """Profile fields; only the fields sent are changed."""

    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None


class UserCreateIn(Schema):
    username: str
    email: str
    password: str | None = None
    first_name: str = ""
    last_name: str = ""


class TokenOut(Schema):
    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class TokenCreateIn(Schema):
    name: str


class TokenCreatedOut(TokenOut):
    key: str
