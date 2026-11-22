from archive.submissions import FixedSubmission, iter_located_rows, match_captured_pages
from archive.transactions import AdmissionReceipt, BatchPublisher
from archive.zone_archive import (
    ZoneAdmissionReceipt,
    ZoneBatchPublisher,
    validate_zone_submission,
)
from capture.completeness import IncompleteEvidence, validate_fixed_chain
from capture.evidence import EvidenceLedger
from capture.jobs import FixedJobs, UnknownTask
from quality.profiles import ProfileRevision, ProfileStore
from quality.results import ReadingResult, evaluate_fixed_rows


class Admission:
    def __init__(self, jobs: FixedJobs, ledger: EvidenceLedger, profiles: ProfileStore,
                 publisher: BatchPublisher, zone_publisher: ZoneBatchPublisher) -> None:
        self.jobs = jobs
        self.ledger = ledger
        self.profiles = profiles
        self.publisher = publisher
        self.zone_publisher = zone_publisher

    def admit(self, task_id: str, package) -> AdmissionReceipt | ZoneAdmissionReceipt:
        if not isinstance(task_id, str) or not task_id:
            raise UnknownTask(f'unknown task {task_id!r}')
        if isinstance(package, dict):
            if set(package) != {'pages', 'coverage'}:
                raise ValueError('zoned package requires exactly pages and coverage')
            pages = tuple(package['pages'])
            coverage = package['coverage']
            submission = FixedSubmission(task_id, pages)
            return self.zone_publisher.publish_zoned(
                submission, coverage, self._prepare_zoned(submission, coverage),
            )
        return self.publisher.publish_fixed(
            FixedSubmission(task_id, tuple(package)), self._prepare,
        )

    def _prepare(self, submission: FixedSubmission) -> tuple[ProfileRevision, tuple[ReadingResult, ...]]:
        job = self.jobs.get(submission.task_id)
        if job.zones is not None:
            raise ValueError(f'task {submission.task_id!r} is a zoned task and requires coverage')
        if not job.complete:
            raise IncompleteEvidence(f'task {job.task_id!r} has not completed capture')
        pages = submission.pages
        validate_fixed_chain(job, pages)
        match_captured_pages(pages, self.ledger.read(job.task_id))
        profile = self.profiles.get(job.profile_revision)
        results = evaluate_fixed_rows((row for _, _, row in iter_located_rows(pages)), profile)
        return profile, results

    def _prepare_zoned(self, submission: FixedSubmission, coverage: object):
        job = self.jobs.get(submission.task_id)
        if job.zones is None:
            raise ValueError(f'task {submission.task_id!r} is not a zoned task')
        if not job.complete:
            raise IncompleteEvidence(f'task {job.task_id!r} has not completed capture')
        pages = submission.pages
        validate_fixed_chain(job, pages)
        match_captured_pages(pages, self.ledger.read(job.task_id))
        grouped_rows = validate_zone_submission(job, pages, coverage)
        profile = self.profiles.get(job.profile_revision)
        return job, profile, grouped_rows
