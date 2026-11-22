from dataclasses import dataclass
from fractions import Fraction

from archive.batches import Batch
from archive.provenance import RowOrigin
from capture.zones import ZoneRange
from quality.results import ReadingResult


@dataclass(frozen=True, slots=True)
class ReportDetail:
    reading: ReadingResult
    origin: RowOrigin


@dataclass(frozen=True, slots=True)
class ReportSelection:
    details: tuple[ReportDetail, ...]
    over_limit_ratio: Fraction | None


@dataclass(frozen=True, slots=True)
class ZoneReport:
    total_count: int
    details: tuple[ReportDetail, ...]
    over_limit_ratio: Fraction | None


def select_over_limit(batch: Batch, origins: tuple[RowOrigin, ...]) -> ReportSelection:
    by_point = {origin.point_id: origin for origin in origins}
    details = tuple(ReportDetail(reading, by_point[reading.source.point_id])
                    for reading in batch.results if reading.over_limit)
    ratio = Fraction(len(details), len(batch.results)) if batch.results else None
    return ReportSelection(details, ratio)


def select_zone_report(results: tuple[ReadingResult, ...],
                       origins: tuple[RowOrigin, ...]) -> ZoneReport:
    """按检区给出总数、编号有序超限明细与精确比例；真正取空的检区比例为空。"""
    by_point = {origin.point_id: origin for origin in origins}
    details = tuple(ReportDetail(reading, by_point[reading.source.point_id])
                    for reading in results if reading.over_limit)
    total = len(results)
    ratio = None if total == 0 else Fraction(len(details), total)
    return ZoneReport(total, details, ratio)


def select_zoned_report(zones: tuple[ZoneRange, ...],
                        zone_results: dict[str, tuple[ReadingResult, ...]],
                        origins: tuple[RowOrigin, ...]) -> dict[str, ZoneReport]:
    return {zone.name: select_zone_report(zone_results[zone.name], origins) for zone in zones}


@dataclass(frozen=True, slots=True)
class ZonedReportSelection:
    details: tuple[ReportDetail, ...]
    over_limit_ratio: Fraction | None
    zones: dict[str, ZoneReport]
