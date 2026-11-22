import sqlite3

from archive.batches import BatchStore
from archive.provenance import BatchProvenance
from handover.reports import Report, ReportStore
from handover.selection import select_over_limit


class ReportSigner:
    def __init__(self, connection: sqlite3.Connection, batches: BatchStore,
                 provenance: BatchProvenance, reports: ReportStore) -> None:
        self.connection = connection
        self.batches = batches
        self.provenance = provenance
        self.reports = reports

    def sign(self, batch_id: int) -> Report:
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            batch = self.batches.require(batch_id)
            previous = self.reports.find_by_batch(batch_id)
            if previous is not None:
                return previous
            _, origins = self.provenance.read(batch_id)
            return self.reports.insert(batch_id, select_over_limit(batch, origins))
