"""多检区授权范围与受限采集的结束证据。

检区是包含端点的整数编号范围；一个任务可在同一固定发布版上登记多个检区。
门户只按检区编号并集交件，受限采集以原发布版的真实页游标续读，
并以发布版真实结束页作为逐区完整性核定的结束证据。
"""
import hashlib
import json
from dataclasses import dataclass

from capture.evidence import EvidencePage, encode_fixed_page
from portal.rows import SourceRow


class InvalidZone(ValueError):
    pass


class ZoneViolation(ValueError):
    pass


class MissingZoneProof(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ZoneRange:
    name: str
    first: int
    last: int

    def contains(self, number: int) -> bool:
        return self.first <= number <= self.last

    def as_pair(self) -> tuple[int, int]:
        return self.first, self.last


def normalize_zones(zones: dict[str, tuple[int, int]] | None) -> tuple[ZoneRange, ...] | None:
    if zones is None:
        return None
    if not isinstance(zones, dict) or not zones:
        raise InvalidZone('zones must be a nonempty mapping of zone name to (first, last)')
    normalized: list[ZoneRange] = []
    names: set[str] = set()
    for name, bounds in zones.items():
        if not isinstance(name, str) or not name:
            raise InvalidZone('zone name must be nonempty text')
        if name in names:
            raise InvalidZone(f'duplicate zone name {name!r}')
        names.add(name)
        if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
            raise InvalidZone(f'zone {name!r} requires a (first, last) pair')
        first, last = bounds
        if type(first) is not int or type(last) is not int:
            raise InvalidZone(f'zone {name!r} bounds must be integers')
        if first > last:
            raise InvalidZone(f'zone {name!r} first number must not exceed last number')
        normalized.append(ZoneRange(name, first, last))
    return tuple(normalized)


def encode_zones(zones: tuple[ZoneRange, ...] | None) -> str | None:
    if zones is None:
        return None
    return json.dumps([[zone.name, zone.first, zone.last] for zone in zones],
                      separators=(',', ':'), ensure_ascii=False)


def decode_zones(payload: str | None) -> tuple[ZoneRange, ...] | None:
    if payload is None:
        return None
    record = json.loads(payload)
    if not isinstance(record, list) or not record:
        raise InvalidZone('stored zone payload has an invalid shape')
    zones = []
    for entry in record:
        if not isinstance(entry, list) or len(entry) != 3:
            raise InvalidZone('stored zone payload has an invalid shape')
        name, first, last = entry
        zones.append(ZoneRange(name, int(first), int(last)))
    return tuple(zones)


def row_in_union(number: int, zones: tuple[ZoneRange, ...]) -> bool:
    return any(zone.contains(number) for zone in zones)


def zone_proof(release_id: str, zone: ZoneRange, terminal: EvidencePage) -> str:
    """绑定发布版、检区范围与受限采集结束证据的逐区证据令牌。"""
    material = json.dumps(
        [release_id, zone.name, zone.first, zone.last, terminal.sequence,
         encode_fixed_page(terminal.page)],
        separators=(',', ':'), ensure_ascii=False,
    )
    return hashlib.sha256(material.encode('utf-8')).hexdigest()


def build_coverage(zones: tuple[ZoneRange, ...], release_id: str,
                   terminal: EvidencePage) -> dict[str, dict]:
    return {
        zone.name: {
            'release_id': release_id,
            'range': [zone.first, zone.last],
            'proof': zone_proof(release_id, zone, terminal),
        }
        for zone in zones
    }


def verify_coverage(coverage: object, zones: tuple[ZoneRange, ...], release_id: str,
                    terminal: EvidencePage) -> None:
    expected = build_coverage(zones, release_id, terminal)
    if not isinstance(coverage, dict) or set(coverage) != set(expected):
        raise MissingZoneProof('coverage must name every registered zone exactly once')
    for zone in zones:
        entry = coverage[zone.name]
        if entry != expected[zone.name]:
            raise MissingZoneProof(f'zone {zone.name!r} proof does not bind the terminal evidence')


def iter_evidence_rows(pages: tuple[EvidencePage, ...]):
    for item in pages:
        for index, row in enumerate(item.page.rows):
            yield item.sequence, index, row


def rows_by_zone(pages: tuple[EvidencePage, ...],
                 zones: tuple[ZoneRange, ...]) -> dict[str, tuple[SourceRow, ...]]:
    grouped: dict[str, list[SourceRow]] = {zone.name: [] for zone in zones}
    seen: set[str] = set()
    for _, _, row in iter_evidence_rows(pages):
        if row.point_id in seen:
            raise ZoneViolation(f'overlapping point {row.point_id!r} is retained more than once')
        seen.add(row.point_id)
        matched = False
        for zone in zones:
            if zone.contains(row.number):
                grouped[zone.name].append(row)
                matched = True
        if not matched:
            raise ZoneViolation(f'point number {row.number} lies outside every authorized zone')
    return {name: tuple(rows) for name, rows in grouped.items()}


def verify_zone_pages(pages: tuple[EvidencePage, ...], job_column: str, job_release: str,
                      zones: tuple[ZoneRange, ...]) -> dict[str, tuple[SourceRow, ...]]:
    """逐区核定受限采集件：错版、越权、重叠重复与结束证据均在此拒绝。"""
    for item in pages:
        page = item.page
        if (page.column, page.release_id) != (job_column, job_release):
            raise ZoneViolation('evidence contains a page from a different fixed release')
    if not pages or not pages[-1].page.last:
        raise MissingZoneProof('restricted capture has no durable terminal page')
    grouped = rows_by_zone(pages, zones)
    for zone in zones:
        for row in grouped[zone.name]:
            if not zone.contains(row.number):
                raise ZoneViolation(f'point number {row.number} is outside zone {zone.name!r}')
    return grouped
