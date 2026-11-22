from dataclasses import dataclass
from fractions import Fraction

from archive.batches import Batch
from archive.provenance import RowOrigin
from quality.results import ReadingResult


@dataclass(frozen=True, slots=True)
class ReportDetail:
    reading: ReadingResult
    origin: RowOrigin


@dataclass(frozen=True, slots=True)
class ReportSelection:
    details: tuple[ReportDetail, ...]
    over_limit_ratio: Fraction | None


def select_over_limit(batch: Batch, origins: tuple[RowOrigin, ...]) -> ReportSelection:
    by_point = {origin.point_id: origin for origin in origins}
    details = tuple(ReportDetail(reading, by_point[reading.source.point_id])
                    for reading in batch.results if reading.over_limit)
    ratio = Fraction(len(details), len(batch.results)) if batch.results else None
    return ReportSelection(details, ratio)
