from collections.abc import Iterable
from dataclasses import dataclass

from portal.rows import SourceRow, normalize_rows


@dataclass(frozen=True, slots=True)
class Release:
    column: str
    release_id: str
    rows: tuple[SourceRow, ...]


def validate_release_key(column: str, release_id: str) -> None:
    if not isinstance(column, str) or not column:
        raise ValueError('column must be nonempty text')
    if not isinstance(release_id, str) or not release_id:
        raise ValueError('release ID must be nonempty text')


def build_release(column: str, release_id: str, rows: Iterable[SourceRow]) -> Release:
    validate_release_key(column, release_id)
    return Release(column, release_id, normalize_rows(rows))
