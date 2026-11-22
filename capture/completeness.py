from capture.evidence import EvidencePage
from capture.jobs import FixedJob
from portal.cursors import InvalidCursor, PageCursor, decode_cursor, encode_cursor
from portal.pages import FixedPage
from portal.rows import SourceRow


class IncompleteEvidence(ValueError):
    pass


class WrongFixedRelease(ValueError):
    pass


class InvalidPageChain(ValueError):
    pass


def validate_fixed_page(job: FixedJob, evidence: EvidencePage, sequence: int, cursor: str | None) -> None:
    if not isinstance(evidence, EvidencePage) or type(evidence.sequence) is not int or evidence.sequence != sequence:
        raise InvalidPageChain(f'expected page sequence {sequence}')
    page = evidence.page
    if not isinstance(page, FixedPage):
        raise InvalidPageChain(f'invalid page at sequence {sequence}')
    if (page.column, page.release_id) != (job.column, job.release_id):
        raise WrongFixedRelease(f'page {sequence} is from a different fixed release')
    if page.request_cursor != cursor:
        raise InvalidPageChain(f'page {sequence} does not follow the previous cursor')
    try:
        previous = None if cursor is None else decode_cursor(cursor, job.column, job.release_id).after
    except InvalidCursor as exc:
        raise InvalidPageChain(f'invalid cursor at page {sequence}') from exc

    if not isinstance(page.rows, tuple) or len(page.rows) > job.page_length or type(page.last) is not bool:
        raise InvalidPageChain(f'invalid size or end marker at page {sequence}')

    restricted = job.zones is not None
    if not restricted and not page.rows and (not page.last or cursor is not None):
        raise InvalidPageChain('only the terminal first page may be empty')
    # 受限采集按授权并集过滤：页内可空，空结束页用于证实已证为空的检区；
    # 游标与结束标记仍必须绑定原发布版，由下方的游标检查核定。

    points: set[str] = set()
    for row in page.rows:
        if not isinstance(row, SourceRow):
            raise InvalidPageChain(f'invalid row at page {sequence}')
        if previous is not None and row.number <= previous:
            raise InvalidPageChain(f'point numbers do not increase at page {sequence}')
        if row.point_id in points:
            raise InvalidPageChain(f'duplicate point ID {row.point_id!r}')
        previous = row.number
        points.add(row.point_id)

    if page.last:
        if page.next_cursor is not None:
            raise InvalidPageChain('terminal page has a continuation cursor')
    elif restricted:
        if page.next_cursor is None:
            raise InvalidPageChain(f'non-terminal page {sequence} lacks a continuation cursor')
        try:
            decode_cursor(page.next_cursor, job.column, job.release_id)
        except InvalidCursor as exc:
            raise InvalidPageChain(f'invalid continuation cursor at page {sequence}') from exc
    else:
        expected = encode_cursor(PageCursor(job.column, job.release_id, page.rows[-1].number))
        if len(page.rows) != job.page_length or page.next_cursor != expected:
            raise InvalidPageChain(f'wrong size or continuation at page {sequence}')


def validate_fixed_chain(job: FixedJob, pages: tuple[EvidencePage, ...]) -> None:
    cursor = None
    seen_points: set[str] = set()
    ended = False
    for sequence, evidence in enumerate(pages, 1):
        if ended:
            raise InvalidPageChain('evidence continues after its terminal page')
        validate_fixed_page(job, evidence, sequence, cursor)
        page = evidence.page
        for row in page.rows:
            if row.point_id in seen_points:
                raise InvalidPageChain(f'duplicate point ID across pages: {row.point_id!r}')
            seen_points.add(row.point_id)
        cursor = page.next_cursor
        ended = page.last
    if not ended:
        raise IncompleteEvidence('submission has no terminal page')
