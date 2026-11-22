import json
from collections.abc import Iterator
from dataclasses import dataclass

from capture.evidence import EvidencePage, encode_fixed_page
from portal.rows import SourceRow


class OriginalPageMismatch(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FixedSubmission:
    task_id: str
    pages: tuple[EvidencePage, ...]


def canonical_submission(pages: tuple[EvidencePage, ...]) -> str:
    return json.dumps([(item.sequence, encode_fixed_page(item.page)) for item in pages], separators=(',', ':'))


def match_captured_pages(submitted: tuple[EvidencePage, ...], captured: tuple[EvidencePage, ...]) -> None:
    originals = {item.sequence: encode_fixed_page(item.page) for item in captured}
    for item in submitted:
        if originals.get(item.sequence) != encode_fixed_page(item.page):
            raise OriginalPageMismatch(f'page {item.sequence} differs from the captured original')


def iter_located_rows(pages: tuple[EvidencePage, ...]) -> Iterator[tuple[int, int, SourceRow]]:
    for item in pages:
        for index, row in enumerate(item.page.rows):
            yield item.sequence, index, row
