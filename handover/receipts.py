import sqlite3

from archive.batches import BatchStore
from archive.provenance import BatchProvenance
from archive.zone_archive import ZoneArchive
from capture.jobs import FixedJobs
from handover.reports import Report, ReportStore
from handover.selection import (
    ZonedReportSelection,
    select_over_limit,
    select_zoned_report,
)


class ReportSigner:
    def __init__(self, connection: sqlite3.Connection, batches: BatchStore,
                 provenance: BatchProvenance, reports: ReportStore,
                 zone_archive: ZoneArchive, jobs: FixedJobs) -> None:
        self.connection = connection
        self.batches = batches
        self.provenance = provenance
        self.reports = reports
        self.zone_archive = zone_archive
        self.jobs = jobs

    def sign(self, batch_id: int) -> Report:
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            batch = self.batches.require(batch_id)
            previous = self.reports.find_by_batch(batch_id)
            if previous is not None:
                return previous
            _, origins = self.provenance.read(batch_id)
            if self.zone_archive.is_zoned(batch_id):
                job = self.jobs.get(batch.task_id)
                zone_results = self.zone_archive.read_zone_results(batch_id, job.zones)
                zones = select_zoned_report(job.zones, zone_results, origins)
                selection = ZonedReportSelection((), None, zones)
                return self.reports.insert(batch_id, selection, zoned=True)
            return self.reports.insert(batch_id, select_over_limit(batch, origins))
