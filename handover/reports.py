import json
import sqlite3
from dataclasses import asdict, dataclass
from fractions import Fraction

from archive.provenance import RowOrigin
from handover.selection import ReportDetail, ZoneReport
from quality.results import ReadingResult


class UnknownReport(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class Report:
    report_id: int
    batch_id: int
    details: tuple[ReportDetail, ...]
    over_limit_ratio: Fraction | None
    zones: dict[str, ZoneReport] | None = None


class ReportStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                report_id INTEGER PRIMARY KEY,
                batch_id INTEGER NOT NULL UNIQUE REFERENCES batches(batch_id),
                report_details TEXT NOT NULL,
                over_limit_ratio TEXT,
                zone_details TEXT
            )
        ''')
        columns = {record[1] for record in self.connection.execute('PRAGMA table_info(reports)')}
        if 'zone_details' not in columns:
            self.connection.execute('ALTER TABLE reports ADD COLUMN zone_details TEXT')

    @staticmethod
    def _encode_detail(detail: ReportDetail) -> dict:
        return {'reading': detail.reading.to_record(), 'origin': asdict(detail.origin)}

    @staticmethod
    def _decode_detail(record: dict) -> ReportDetail:
        return ReportDetail(ReadingResult.from_record(record['reading']), RowOrigin(**record['origin']))

    @staticmethod
    def _encode_zones(zones: dict[str, ZoneReport] | None) -> str | None:
        if zones is None:
            return None
        return json.dumps({
            name: {
                'total_count': zone.total_count,
                'details': [ReportStore._encode_detail(detail) for detail in zone.details],
                'over_limit_ratio': None if zone.over_limit_ratio is None else str(zone.over_limit_ratio),
            }
            for name, zone in zones.items()
        }, ensure_ascii=False)

    @staticmethod
    def _decode_zones(payload: str | None) -> dict[str, ZoneReport] | None:
        if payload is None:
            return None
        record = json.loads(payload)
        return {
            name: ZoneReport(
                entry['total_count'],
                tuple(ReportStore._decode_detail(detail) for detail in entry['details']),
                None if entry['over_limit_ratio'] is None else Fraction(entry['over_limit_ratio']),
            )
            for name, entry in record.items()
        }

    def insert(self, batch_id: int, selection, *, zoned: bool = False) -> Report:
        ratio = selection.over_limit_ratio
        encoded_ratio = None if ratio is None else str(ratio)
        details = [self._encode_detail(detail) for detail in selection.details]
        zone_payload = self._encode_zones(getattr(selection, 'zones', None))
        cursor = self.connection.execute('''
            INSERT INTO reports (batch_id, report_details, over_limit_ratio, zone_details)
            VALUES (?, ?, ?, ?)
        ''', (batch_id, json.dumps(details), encoded_ratio, zone_payload))
        zones = getattr(selection, 'zones', None) if zoned else None
        return Report(cursor.lastrowid, batch_id, selection.details, ratio, zones)

    def _decode(self, row: tuple) -> Report:
        report_id, batch_id, details, ratio, zone_payload = row
        decoded = tuple(self._decode_detail(detail) for detail in json.loads(details))
        return Report(report_id, batch_id, decoded,
                      None if ratio is None else Fraction(ratio),
                      self._decode_zones(zone_payload))

    def find_by_batch(self, batch_id: int) -> Report | None:
        row = self.connection.execute('''
            SELECT report_id, batch_id, report_details, over_limit_ratio, zone_details
            FROM reports WHERE batch_id = ?
        ''', (batch_id,)).fetchone()
        return None if row is None else self._decode(row)

    def require(self, report_id: int) -> Report:
        if type(report_id) is not int or not 0 < report_id < 2**63:
            raise UnknownReport(f'unknown report {report_id!r}')
        row = self.connection.execute('''
            SELECT report_id, batch_id, report_details, over_limit_ratio, zone_details
            FROM reports WHERE report_id = ?
        ''', (report_id,)).fetchone()
        if row is None:
            raise UnknownReport(f'unknown report {report_id}')
        return self._decode(row)
