import json
import sqlite3
from dataclasses import asdict, dataclass
from fractions import Fraction

from archive.provenance import RowOrigin
from handover.selection import ReportDetail, ReportSelection
from quality.results import ReadingResult


class UnknownReport(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class Report:
    report_id: int
    batch_id: int
    details: tuple[ReportDetail, ...]
    over_limit_ratio: Fraction | None


class ReportStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                report_id INTEGER PRIMARY KEY,
                batch_id INTEGER NOT NULL UNIQUE REFERENCES batches(batch_id),
                report_details TEXT NOT NULL,
                over_limit_ratio TEXT
            )
        ''')

    def insert(self, batch_id: int, selection: ReportSelection) -> Report:
        ratio = selection.over_limit_ratio
        encoded_ratio = None if ratio is None else str(ratio)
        details = [{'reading': detail.reading.to_record(), 'origin': asdict(detail.origin)}
                   for detail in selection.details]
        cursor = self.connection.execute('''
            INSERT INTO reports (batch_id, report_details, over_limit_ratio) VALUES (?, ?, ?)
        ''', (batch_id, json.dumps(details), encoded_ratio))
        return Report(cursor.lastrowid, batch_id, selection.details, ratio)

    @staticmethod
    def _decode(row: tuple) -> Report:
        report_id, batch_id, details, ratio = row
        decoded = tuple(ReportDetail(ReadingResult.from_record(detail['reading']), RowOrigin(**detail['origin']))
                        for detail in json.loads(details))
        return Report(report_id, batch_id, decoded, None if ratio is None else Fraction(ratio))

    def find_by_batch(self, batch_id: int) -> Report | None:
        row = self.connection.execute('''
            SELECT report_id, batch_id, report_details, over_limit_ratio FROM reports WHERE batch_id = ?
        ''', (batch_id,)).fetchone()
        return None if row is None else self._decode(row)

    def require(self, report_id: int) -> Report:
        if type(report_id) is not int or not 0 < report_id < 2**63:
            raise UnknownReport(f'unknown report {report_id!r}')
        row = self.connection.execute('''
            SELECT report_id, batch_id, report_details, over_limit_ratio FROM reports WHERE report_id = ?
        ''', (report_id,)).fetchone()
        if row is None:
            raise UnknownReport(f'unknown report {report_id}')
        return self._decode(row)
