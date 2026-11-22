import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from archive.batches import Batch, BatchStore
from archive.provenance import BatchProvenance, RowOrigin
from archive.submissions import FixedSubmission, canonical_submission
from capture.evidence import EvidencePage
from quality.profiles import ProfileRevision
from quality.results import ReadingResult


class SubmissionConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AdmissionReceipt:
    batch: Batch
    pages: tuple[EvidencePage, ...]
    origins: tuple[RowOrigin, ...]


class BatchPublisher:
    def __init__(self, connection: sqlite3.Connection, batches: BatchStore, provenance: BatchProvenance) -> None:
        self.connection = connection
        self.batches = batches
        self.provenance = provenance

    def publish_fixed(self, submission: FixedSubmission,
                      prepare: Callable[[FixedSubmission], tuple[ProfileRevision, tuple[ReadingResult, ...]]]
                      ) -> AdmissionReceipt:
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            receipt = self._publish(submission, prepare)
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return receipt

    def _publish(self, submission: FixedSubmission,
                 prepare: Callable[[FixedSubmission], tuple[ProfileRevision, tuple[ReadingResult, ...]]]
                 ) -> AdmissionReceipt:
        previous = self.batches.find_by_task(submission.task_id)
        if previous is not None:
            original, origins = self.provenance.read(previous.batch_id)
            if canonical_submission(submission.pages) != canonical_submission(original):
                raise SubmissionConflict(f'conflicting submission for task {submission.task_id!r}')
            return AdmissionReceipt(previous, original, origins)

        profile, results = prepare(submission)
        opening = submission.pages[0].page
        batch = self.batches.insert(submission.task_id, opening.column, opening.release_id, profile, results)
        origins = self.provenance.store(batch.batch_id, submission.pages)
        return AdmissionReceipt(batch, submission.pages, origins)
