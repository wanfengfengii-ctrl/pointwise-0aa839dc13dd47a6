"""多检区任务的正式归档、逐区核定与原子发布。"""
import json
import sqlite3
from dataclasses import dataclass

from archive.batches import Batch, BatchStore
from archive.provenance import BatchProvenance, RowOrigin
from archive.submissions import FixedSubmission, canonical_submission, iter_located_rows
from archive.transactions import SubmissionConflict
from capture.evidence import EvidencePage
from capture.zones import (
    MissingZoneProof,
    ZoneRange,
    verify_coverage,
    verify_zone_pages,
)
from quality.profiles import ProfileRevision
from quality.results import ReadingResult, evaluate_fixed_rows


@dataclass(frozen=True, slots=True)
class ZoneAdmissionReceipt:
    batch: Batch
    pages: tuple[EvidencePage, ...]
    origins: tuple[RowOrigin, ...]
    coverage: dict[str, dict]
    zone_results: dict[str, tuple[ReadingResult, ...]]


class ZoneArchive:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def initialize(self) -> None:
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS zone_coverage (
                batch_id INTEGER NOT NULL REFERENCES batches(batch_id),
                zone_name TEXT NOT NULL,
                release_id TEXT NOT NULL,
                range_first INTEGER NOT NULL,
                range_last INTEGER NOT NULL,
                proof TEXT NOT NULL,
                PRIMARY KEY (batch_id, zone_name)
            );
            CREATE TABLE IF NOT EXISTS zone_readings (
                batch_id INTEGER NOT NULL,
                zone_name TEXT NOT NULL,
                ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
                result TEXT NOT NULL,
                PRIMARY KEY (batch_id, zone_name, ordinal)
            );
        ''')

    def store(self, batch_id: int, zones: tuple[ZoneRange, ...],
              coverage: dict[str, dict],
              zone_results: dict[str, tuple[ReadingResult, ...]]) -> None:
        self.connection.executemany('''
            INSERT INTO zone_coverage (batch_id, zone_name, release_id, range_first, range_last, proof)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ((batch_id, zone.name, coverage[zone.name]['release_id'],
               zone.first, zone.last, coverage[zone.name]['proof']) for zone in zones))
        self.connection.executemany('''
            INSERT INTO zone_readings (batch_id, zone_name, ordinal, result)
            VALUES (?, ?, ?, ?)
        ''', ((batch_id, zone.name, ordinal, json.dumps(result.to_record()))
              for zone in zones
              for ordinal, result in enumerate(zone_results[zone.name])))

    def is_zoned(self, batch_id: int) -> bool:
        row = self.connection.execute(
            'SELECT 1 FROM zone_coverage WHERE batch_id = ? LIMIT 1', (batch_id,),
        ).fetchone()
        return row is not None

    def read_coverage(self, batch_id: int) -> dict[str, dict]:
        records = self.connection.execute('''
            SELECT zone_name, release_id, range_first, range_last, proof
            FROM zone_coverage WHERE batch_id = ? ORDER BY zone_name
        ''', (batch_id,))
        return {
            name: {'release_id': release_id, 'range': [first, last], 'proof': proof}
            for name, release_id, first, last, proof in records
        }

    def read_zone_results(self, batch_id: int, zones: tuple[ZoneRange, ...]) -> dict[str, tuple[ReadingResult, ...]]:
        outcome: dict[str, tuple[ReadingResult, ...]] = {}
        for zone in zones:
            records = self.connection.execute('''
                SELECT result FROM zone_readings
                WHERE batch_id = ? AND zone_name = ? ORDER BY ordinal
            ''', (batch_id, zone.name))
            outcome[zone.name] = tuple(
                ReadingResult.from_record(json.loads(payload)) for (payload,) in records
            )
        return outcome


class ZoneBatchPublisher:
    def __init__(self, connection: sqlite3.Connection, batches: BatchStore,
                 provenance: BatchProvenance, zones_archive: ZoneArchive) -> None:
        self.connection = connection
        self.batches = batches
        self.provenance = provenance
        self.zones_archive = zones_archive

    def publish_zoned(self, submission: FixedSubmission, coverage: dict[str, dict],
                      prepared: tuple) -> ZoneAdmissionReceipt:
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            receipt = self._publish(submission, coverage, *prepared)
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return receipt

    def _publish(self, submission: FixedSubmission, coverage: dict[str, dict],
                 job, profile: ProfileRevision,
                 grouped_rows: dict[str, tuple]) -> ZoneAdmissionReceipt:
        previous = self.batches.find_by_task(submission.task_id)
        if previous is not None:
            original, origins = self.provenance.read(previous.batch_id)
            if canonical_submission(submission.pages) != canonical_submission(original):
                raise SubmissionConflict(f'conflicting submission for task {submission.task_id!r}')
            stored_coverage = self.zones_archive.read_coverage(previous.batch_id)
            if stored_coverage != coverage:
                raise SubmissionConflict(f'conflicting zone coverage for task {submission.task_id!r}')
            return ZoneAdmissionReceipt(
                previous, original, origins, stored_coverage,
                self.zones_archive.read_zone_results(previous.batch_id, job.zones),
            )

        zone_results = {
            zone.name: evaluate_fixed_rows(grouped_rows[zone.name], profile) for zone in job.zones
        }
        union_rows = tuple(row for _, _, row in iter_located_rows(submission.pages))
        union_results = evaluate_fixed_rows(union_rows, profile)
        opening = submission.pages[0].page
        batch = self.batches.insert(submission.task_id, opening.column, opening.release_id,
                                    profile, union_results)
        origins = self.provenance.store(batch.batch_id, submission.pages)
        self.zones_archive.store(batch.batch_id, job.zones, coverage, zone_results)
        return ZoneAdmissionReceipt(batch, submission.pages, origins, coverage, zone_results)


def validate_zone_submission(job, pages: tuple[EvidencePage, ...],
                             coverage: object) -> dict[str, tuple]:
    """错版、越权、缺证与篡改在进入事务前逐区核定。"""
    if not isinstance(coverage, dict):
        raise MissingZoneProof('zoned task requires a coverage mapping')
    grouped = verify_zone_pages(pages, job.column, job.release_id, job.zones)
    verify_coverage(coverage, job.zones, job.release_id, pages[-1])
    return grouped
