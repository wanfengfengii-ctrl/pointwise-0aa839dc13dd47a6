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

    def restricted_page(self, column: str, release_id: str, cursor: str | None,
                        page_length: int, authorized) -> FixedPage:
        """按授权编号谓词交件的受限采集页。

        游标仍为发布版真实页游标，保证续读与结束证据绑定原发布版；范围外
        编号在门户侧即被剔除，绝不进入站库。过滤后页内可能为空，只有发布版
        真正读到末页时才置结束标记，空结束页用于证实合法空区。
        """
        page = self.page(column, release_id, cursor, page_length)
        rows = tuple(row for row in page.rows if authorized(row.number))
        return FixedPage(column, release_id, page.request_cursor, page.next_cursor, page.last, rows)
