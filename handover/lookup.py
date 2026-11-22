from dataclasses import dataclass

from archive.batches import Batch, BatchStore
from archive.provenance import BatchProvenance, RowOrigin
from archive.zone_archive import ZoneArchive
from capture.evidence import EvidencePage
from handover.reports import Report, ReportStore


@dataclass(frozen=True, slots=True)
class ReportReceipt:
    report: Report
    batch: Batch
    pages: tuple[EvidencePage, ...]
    origins: tuple[RowOrigin, ...]
    coverage: dict[str, dict] | None = None


class ReportLookup:
    def __init__(self, reports: ReportStore, batches: BatchStore,
                 provenance: BatchProvenance, zone_archive: ZoneArchive) -> None:
        self.reports = reports
        self.batches = batches
        self.provenance = provenance
        self.zone_archive = zone_archive

    def lookup(self, report_id: int) -> ReportReceipt:
        report = self.reports.require(report_id)
        batch = self.batches.require(report.batch_id)
        pages, origins = self.provenance.read(batch.batch_id)
        coverage = None
        if report.zones is not None:
            coverage = self.zone_archive.read_coverage(batch.batch_id)
        return ReportReceipt(report, batch, pages, origins, coverage)
