from collections.abc import Iterable
from dataclasses import dataclass
from operator import attrgetter


class InvalidSourceRows(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SourceRow:
    point_id: str
    number: int
    raw: int
    source_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.point_id, str) or not self.point_id:
            raise InvalidSourceRows('point ID must be nonempty text')
        if not isinstance(self.source_version, str) or not self.source_version:
            raise InvalidSourceRows('source version must be nonempty text')
        if type(self.number) is not int or type(self.raw) is not int:
            raise InvalidSourceRows('point number and raw reading must be integers')


def normalize_rows(rows: Iterable[SourceRow]) -> tuple[SourceRow, ...]:
    points: set[str] = set()
    numbers: set[int] = set()
    normalized = []
    for row in rows:
        if not isinstance(row, SourceRow):
            raise InvalidSourceRows('a release requires SourceRow entries')
        if row.point_id in points:
            raise InvalidSourceRows(f'duplicate point ID {row.point_id!r}')
        if row.number in numbers:
            raise InvalidSourceRows(f'duplicate point number {row.number}')
        points.add(row.point_id)
        numbers.add(row.number)
        normalized.append(row)
    return tuple(sorted(normalized, key=attrgetter('number')))
