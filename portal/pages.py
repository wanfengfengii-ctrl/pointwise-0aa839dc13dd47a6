from bisect import bisect_right
from dataclasses import dataclass
from operator import attrgetter

from portal.catalog import Catalog
from portal.cursors import InvalidCursor, PageCursor, decode_cursor, encode_cursor
from portal.rows import SourceRow


class InvalidPageLength(ValueError):
    pass


def validate_page_length(page_length: int) -> None:
    if type(page_length) is not int or page_length <= 0:
        raise InvalidPageLength('page length must be a positive integer')


@dataclass(frozen=True, slots=True)
class FixedPage:
    column: str
    release_id: str
    request_cursor: str | None
    next_cursor: str | None
    last: bool
    rows: tuple[SourceRow, ...]


class FixedPortal:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def close(self) -> None:
        self.catalog.connection.close()

    def page(self, column: str, release_id: str, cursor: str | None, page_length: int) -> FixedPage:
        validate_page_length(page_length)
        release = self.catalog.require_release(column, release_id)
        start = 0
        if cursor is not None:
            anchor = decode_cursor(cursor, column, release_id).after
            start = bisect_right(release.rows, anchor, key=attrgetter('number'))
            if start == 0 or release.rows[start - 1].number != anchor:
                raise InvalidCursor('cursor anchor is absent from the release')

        end = min(start + page_length, len(release.rows))
        rows = release.rows[start:end]
        last = end == len(release.rows)
        next_cursor = None if last else encode_cursor(PageCursor(column, release_id, rows[-1].number))
        return FixedPage(column, release_id, cursor, next_cursor, last, rows)
