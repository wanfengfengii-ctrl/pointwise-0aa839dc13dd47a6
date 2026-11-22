from dataclasses import dataclass

from archive.batches import Batch, BatchStore
from archive.provenance import BatchProvenance, RowOrigin
from capture.evidence import EvidencePage
from handover.reports import Report, ReportStore


@dataclass(frozen=True, slots=True)
class ReportReceipt:
    report: Report
    batch: Batch
    pages: tuple[EvidencePage, ...]
    origins: tuple[RowOrigin, ...]


class ReportLookup:
    def __init__(self, reports: ReportStore, batches: BatchStore, provenance: BatchProvenance) -> None:
        self.reports = reports
        self.batches = batches
        self.provenance = provenance

    def lookup(self, report_id: int) -> ReportReceipt:
        report = self.reports.require(report_id)
        batch = self.batches.require(report.batch_id)
        pages, origins = self.provenance.read(batch.batch_id)
        return ReportReceipt(report, batch, pages, origins)
