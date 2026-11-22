from collections.abc import Iterable

from archive.submissions import FixedSubmission, iter_located_rows, match_captured_pages
from archive.transactions import AdmissionReceipt, BatchPublisher
from capture.completeness import IncompleteEvidence, validate_fixed_chain
from capture.evidence import EvidenceLedger, EvidencePage
from capture.jobs import FixedJobs, UnknownTask
from quality.profiles import ProfileRevision, ProfileStore
from quality.results import ReadingResult, evaluate_fixed_rows


class Admission:
    def __init__(self, jobs: FixedJobs, ledger: EvidenceLedger, profiles: ProfileStore,
                 publisher: BatchPublisher) -> None:
        self.jobs = jobs
        self.ledger = ledger
        self.profiles = profiles
        self.publisher = publisher

    def admit(self, task_id: str, pages: Iterable[EvidencePage]) -> AdmissionReceipt:
        if not isinstance(task_id, str) or not task_id:
            raise UnknownTask(f'unknown task {task_id!r}')
        return self.publisher.publish_fixed(FixedSubmission(task_id, tuple(pages)), self._prepare)

    def _prepare(self, submission: FixedSubmission) -> tuple[ProfileRevision, tuple[ReadingResult, ...]]:
        job = self.jobs.get(submission.task_id)
        if not job.complete:
            raise IncompleteEvidence(f'task {job.task_id!r} has not completed capture')
        pages = submission.pages
        validate_fixed_chain(job, pages)
        match_captured_pages(pages, self.ledger.read(job.task_id))
        profile = self.profiles.get(job.profile_revision)
        results = evaluate_fixed_rows((row for _, _, row in iter_located_rows(pages)), profile)
        return profile, results
