from dataclasses import dataclass

from capture.checkpoints import CaptureCheckpoints
from capture.completeness import IncompleteEvidence
from capture.evidence import EvidenceLedger
from capture.jobs import FixedJob, FixedJobs
from capture.zones import build_coverage, row_in_union
from portal.pages import FixedPortal, validate_page_length


@dataclass(frozen=True, slots=True)
class PullProgress:
    task_id: str
    pages_read: int
    next_cursor: str | None
    complete: bool


class FixedCapture:
    def __init__(self, portal: FixedPortal, jobs: FixedJobs, ledger: EvidenceLedger,
                 checkpoints: CaptureCheckpoints, page_length: int) -> None:
        validate_page_length(page_length)
        self.portal = portal
        self.jobs = jobs
        self.ledger = ledger
        self.checkpoints = checkpoints
        self.page_length = page_length

    def start_fixed(self, task_id: str, column: str, release_id: str, revision: str, *,
                    zones: dict[str, tuple[int, int]] | None = None) -> FixedJob:
        return self.jobs.start_fixed(task_id, column, release_id, revision,
                                     catalog=self.portal.catalog, page_length=self.page_length,
                                     zones=zones)

    def _read_page(self, job: FixedJob):
        if job.zones is None:
            return self.portal.page(job.column, job.release_id, job.next_cursor, job.page_length)
        return self.portal.restricted_page(
            job.column, job.release_id, job.next_cursor, job.page_length,
            lambda number: row_in_union(number, job.zones),
        )

    def pull(self, task_id: str) -> PullProgress:
        job = self.jobs.get(task_id)
        if not job.complete:
            page = self._read_page(job)
            job = self.checkpoints.advance(job, page)
        return PullProgress(job.task_id, job.pages_read, job.next_cursor, job.complete)

    def evidence_for(self, task_id: str):
        job = self.jobs.get(task_id)
        if not job.complete:
            raise IncompleteEvidence(f'task {task_id!r} has no durable terminal page')
        pages = self.ledger.read(task_id)
        if job.zones is None:
            return pages
        return {
            'pages': pages,
            'coverage': build_coverage(job.zones, job.release_id, pages[-1]),
        }
