from collections.abc import Iterable
from dataclasses import asdict, dataclass
from fractions import Fraction
from operator import attrgetter

from portal.rows import SourceRow
from quality.conversion import to_micrometres
from quality.limits import is_over_limit
from quality.profiles import ProfileRevision


@dataclass(frozen=True, slots=True)
class ReadingResult:
    source: SourceRow
    micrometres: Fraction
    over_limit: bool

    def to_record(self) -> dict:
        return {
            'source': asdict(self.source),
            'micrometres': [self.micrometres.numerator, self.micrometres.denominator],
            'over_limit': self.over_limit,
        }

    @classmethod
    def from_record(cls, record: dict) -> 'ReadingResult':
        return cls(SourceRow(**record['source']), Fraction(*record['micrometres']), record['over_limit'])


def evaluate_fixed_rows(rows: Iterable[SourceRow], profile: ProfileRevision) -> tuple[ReadingResult, ...]:
    results = []
    for row in sorted(rows, key=attrgetter('number')):
        value = to_micrometres(row.raw, profile)
        results.append(ReadingResult(row, value, is_over_limit(value, profile.limit)))
    return tuple(results)
