from dataclasses import dataclass

from capture.checkpoints import CaptureCheckpoints
from capture.completeness import IncompleteEvidence
from capture.evidence import EvidenceLedger, EvidencePage
from capture.jobs import FixedJob, FixedJobs
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

    def start_fixed(self, task_id: str, column: str, release_id: str, revision: str) -> FixedJob:
        return self.jobs.start_fixed(task_id, column, release_id, revision,
                                     catalog=self.portal.catalog, page_length=self.page_length)

    def pull(self, task_id: str) -> PullProgress:
        job = self.jobs.get(task_id)
        if not job.complete:
            page = self.portal.page(job.column, job.release_id, job.next_cursor, job.page_length)
            job = self.checkpoints.advance(job, page)
        return PullProgress(job.task_id, job.pages_read, job.next_cursor, job.complete)

    def evidence_for(self, task_id: str) -> tuple[EvidencePage, ...]:
        if not self.jobs.get(task_id).complete:
            raise IncompleteEvidence(f'task {task_id!r} has no durable terminal page')
        return self.ledger.read(task_id)
