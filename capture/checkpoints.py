import sqlite3
from dataclasses import replace

from capture.completeness import validate_fixed_page
from capture.evidence import EvidenceLedger, EvidencePage
from capture.jobs import FixedJob, FixedJobs
from portal.pages import FixedPage


class StaleCheckpoint(ValueError):
    pass


class CaptureCheckpoints:
    def __init__(self, connection: sqlite3.Connection, jobs: FixedJobs, ledger: EvidenceLedger) -> None:
        self.connection = connection
        self.jobs = jobs
        self.ledger = ledger

    def advance(self, expected: FixedJob, page: FixedPage) -> FixedJob:
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            current = self.jobs.get(expected.task_id)
            if current != expected or current.complete:
                raise StaleCheckpoint(f'checkpoint already advanced for {expected.task_id!r}')
            sequence = current.pages_read + 1
            evidence = EvidencePage(sequence, page)
            validate_fixed_page(current, evidence, sequence, current.next_cursor)
            self.ledger.append(current.task_id, evidence)
            self.connection.execute('''
                UPDATE fixed_jobs SET pages_read = ?, next_cursor = ?, complete = ? WHERE task_id = ?
            ''', (sequence, page.next_cursor, int(page.last), current.task_id))
            return replace(current, pages_read=sequence, next_cursor=page.next_cursor, complete=page.last)
