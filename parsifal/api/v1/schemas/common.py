from ninja import Schema


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
