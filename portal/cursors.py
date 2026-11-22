import json
from dataclasses import dataclass


class InvalidCursor(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PageCursor:
    column: str
    release_id: str
    after: int

    def __post_init__(self) -> None:
        if not isinstance(self.column, str) or not self.column:
            raise InvalidCursor('cursor column must be nonempty text')
        if not isinstance(self.release_id, str) or not self.release_id:
            raise InvalidCursor('cursor release ID must be nonempty text')
        if type(self.after) is not int:
            raise InvalidCursor('cursor anchor must be an integer')


def encode_cursor(cursor: PageCursor) -> str:
    return json.dumps([cursor.column, cursor.release_id, cursor.after], separators=(',', ':'))


def decode_cursor(token: str, column: str, release_id: str) -> PageCursor:
    if not isinstance(token, str):
        raise InvalidCursor('cursor must be text')
    try:
        data = json.loads(token)
    except ValueError as exc:
        raise InvalidCursor('invalid cursor encoding') from exc
    if not isinstance(data, list) or len(data) != 3:
        raise InvalidCursor('invalid cursor shape')
    cursor = PageCursor(*data)
    if (cursor.column, cursor.release_id) != (column, release_id):
        raise InvalidCursor('cursor belongs to a different column or release')
    return cursor
