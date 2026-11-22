import sqlite3
from dataclasses import replace

from capture.checkpoints import StaleCheckpoint
from capture.completeness import IncompleteEvidence, InvalidPageChain
from capture.jobs import TaskConflict, UnknownTask
from handover.station import open_portal
from portal.catalog import ReleaseConflict, UnknownRelease
from portal.cursors import InvalidCursor, PageCursor, decode_cursor, encode_cursor
from portal.pages import InvalidPageLength
from portal.rows import InvalidSourceRows, SourceRow
from quality.profiles import UnknownProfile
from tests import StationCase


class CaptureTests(StationCase):
    def test_v1_release_identity(self):
        catalog = self.portal.catalog
        original = catalog.require_release(self.column, 'r1')
        self.assertEqual(catalog.publish(self.column, 'r1', reversed(self.rows)), original)
        with self.assertRaises(InvalidSourceRows):
            catalog.publish(self.column, 'duplicate-id', (*self.rows, SourceRow('A', 40, 9, 'A-2')))
        with self.assertRaises(InvalidSourceRows):
            catalog.publish(self.column, 'duplicate-number', (*self.rows, SourceRow('D', 20, 9, 'D-1')))
        for name in ('duplicate-id', 'duplicate-number'):
            with self.assertRaises(UnknownRelease):
                catalog.require_release(self.column, name)
        with self.assertRaises(ReleaseConflict):
            catalog.publish(self.column, 'r1', (replace(self.rows[0], raw=100), *self.rows[1:]))
        newer = catalog.publish(self.column, 'r2', (SourceRow('A', 5, 8, 'A-2'),))
        self.assertEqual(newer.release_id, 'r2')
        self.assertEqual(self.portal.page(self.column, 'r1', None, 4).rows, self.rows)
        self.assertEqual(self.portal.page(self.column, 'r2', None, 4).rows, newer.rows)

    def test_v1_scoped_cursor(self):
        self.portal.catalog.publish(self.column, 'r2', self.rows)
        self.portal.catalog.publish('south-river', 'r1', self.rows)
        token = self.portal.page(self.column, 'r1', None, 2).next_cursor
        for column, release in ((self.column, 'r2'), ('south-river', 'r1')):
            with self.subTest(column=column, release=release), self.assertRaises(InvalidCursor):
                self.portal.page(column, release, token, 2)
        with self.assertRaises(InvalidCursor):
            self.portal.page(self.column, 'r1', encode_cursor(PageCursor(self.column, 'r1', 15)), 2)
        with self.assertRaises(InvalidCursor):
            self.portal.page(self.column, 'r1', 'unparseable', 2)
        with self.assertRaises(UnknownRelease):
            self.portal.page(self.column, 'missing', None, 2)
        for length in (0, -1, True, 1.5):
            with self.subTest(length=length), self.assertRaises(InvalidPageLength):
                self.portal.page(self.column, 'r1', None, length)

    def test_v1_cursor_boundary(self):
        first = self.portal.page(self.column, 'r1', None, 2)
        self.assertEqual([row.number for row in first.rows], [10, 20])
        self.assertFalse(first.last)
        self.assertEqual(decode_cursor(first.next_cursor, self.column, 'r1').after, 20)
        last = self.portal.page(self.column, 'r1', first.next_cursor, 2)
        self.assertEqual([row.number for row in last.rows], [30])
        self.assertTrue(last.last)
        self.assertIsNone(last.next_cursor)
        retained = self.collect()
        self.assertEqual([item.sequence for item in retained], [1, 2])
        self.assertEqual(tuple(item.page for item in retained), (first, last))
        self.assertTrue(self.station.jobs.get('job').complete)

    def test_v1_registration(self):
        capture = self.station.capture_from(self.portal, page_length=2)
        job = capture.start_fixed('task', self.column, 'r1', 'p1')
        self.assertEqual((job.task_id, job.column, job.release_id, job.profile_revision),
                         ('task', self.column, 'r1', 'p1'))
        self.assertEqual((job.pages_read, job.next_cursor, job.complete), (0, None, False))
        self.assertEqual(capture.start_fixed('task', self.column, 'r1', 'p1'), job)
        with self.assertRaises(IncompleteEvidence):
            capture.evidence_for('task')
        capture.pull('task')
        checkpoint = self.station.jobs.get('task')
        captured = self.station.evidence.read('task')
        changed_config = self.station.capture_from(self.portal, page_length=7)
        self.assertEqual(changed_config.start_fixed('task', self.column, 'r1', 'p1'), checkpoint)
        self.assertEqual(checkpoint.page_length, 2)
        self.station.profiles.set_profile('p2', 2, 0, 9)
        with self.assertRaises(TaskConflict):
            capture.start_fixed('task', self.column, 'r1', 'p2')
        with self.assertRaises(UnknownRelease):
            capture.start_fixed('unknown-release', self.column, 'r9', 'p1')
        with self.assertRaises(UnknownProfile):
            capture.start_fixed('unknown-profile', self.column, 'r1', 'p9')
        for task in ('unknown-release', 'unknown-profile'):
            with self.assertRaises(UnknownTask):
                capture.pull(task)
        self.assertEqual(self.station.jobs.get('task'), checkpoint)
        self.assertEqual(self.station.evidence.read('task'), captured)

    def test_v2_read_failure_and_restart(self):
        capture = self.station.capture_from(self.portal, page_length=2)
        capture.start_fixed('old', self.column, 'r1', 'p1')
        first = capture.pull('old')
        checkpoint = self.station.jobs.get('old')
        evidence = self.station.evidence.read('old')
        self.assertEqual(len(evidence), 1)
        self.assertEqual(first.next_cursor, evidence[0].page.next_cursor)
        self.portal.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            capture.pull('old')
        self.assertEqual(self.station.jobs.get('old'), checkpoint)
        self.assertEqual(self.station.evidence.read('old'), evidence)

        self.portal = open_portal(self.portal_path)
        self.addCleanup(self.portal.close)
        self.portal.catalog.publish(self.column, 'r2', (SourceRow('A', 3, 99, 'A-2'),))
        self.station.close()
        self.reopen_station()
        continuation = self.station.capture_from(self.portal, page_length=1)
        self.assertEqual(continuation.start_fixed('old', self.column, 'r1', 'p1'), checkpoint)
        finished = continuation.pull('old')
        self.assertTrue(finished.complete)
        self.assertEqual(finished.pages_read, 2)
        pages = continuation.evidence_for('old')
        self.assertEqual(pages[:1], evidence)
        self.assertEqual(pages[1].page.request_cursor, first.next_cursor)
        self.assertEqual(pages[1].page.release_id, 'r1')
        self.assertEqual(pages[1].page.rows, (self.rows[2],))
        self.portal.close()
        self.assertEqual(continuation.pull('old'), finished)
        self.assertEqual(continuation.evidence_for('old'), pages)

    def test_checkpoint_rejects_wrong_and_stale_responses(self):
        capture = self.station.capture_from(self.portal)
        starting = capture.start_fixed('job', self.column, 'r1', 'p1')
        first = self.portal.page(self.column, 'r1', None, 2)
        with self.assertRaises(InvalidPageChain):
            self.station.checkpoints.advance(starting, replace(first, request_cursor='wrong'))
        self.assertEqual(self.station.jobs.get('job'), starting)
        self.assertEqual(self.station.evidence.read('job'), ())
        capture.pull('job')
        advanced = self.station.jobs.get('job')
        with self.assertRaises(StaleCheckpoint):
            self.station.checkpoints.advance(starting, first)
        self.assertEqual(self.station.jobs.get('job'), advanced)
        self.assertEqual(len(self.station.evidence.read('job')), 1)
