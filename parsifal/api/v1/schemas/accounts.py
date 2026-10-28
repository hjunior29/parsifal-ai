from datetime import datetime

from ninja import Schema

from parsifal.api.v1.schemas.common import UserOut


class MeOut(UserOut):
    active_tokens: int
    # The columns of the study list on Study Selection, in order (star, bibtex_key, title, author, journal, year,
    # source, doi, document_type, language, publisher, criteria, ai_relevance, created_by, created_at, updated_by,
    # updated_at, status).
    study_columns: list[str]
    theme: str  # system (as the device is set), light or dark


class MeUpdateIn(Schema):
    """Profile fields; only the fields sent are changed."""

    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    study_columns: list[str] | None = None  # the columns of the study list, in order (see me)
    theme: str | None = None  # system, light or dark


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


class LibraryAccessIn(Schema):
    # The proxy's address (ezNN.periodicos.capes.gov.br) or that of any page opened through it, as the browser shows
    # it when signed in to CAPES through CAFe; only the proxy's address is kept.
    address: str


class LibraryAccessOut(Schema):
    configured: bool
    proxy: str | None = None  # e.g. ezNN.periodicos.capes.gov.br
    label: str | None = None  # the link's name in the study window: "Via CAPES", or "Via proxy" for another library
    updated_at: datetime | None = None
