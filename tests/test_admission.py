import sqlite3
from contextlib import closing
from dataclasses import replace
from fractions import Fraction

from archive.batches import UnknownBatch
from archive.submissions import OriginalPageMismatch
from archive.transactions import SubmissionConflict
from capture.completeness import IncompleteEvidence, InvalidPageChain, WrongFixedRelease
from capture.jobs import UnknownTask
from handover.station import open_station
from portal.rows import SourceRow
from quality.profiles import InvalidProfile, ProfileConflict
from tests import StationCase


class AdmissionTests(StationCase):
    @staticmethod
    def changed_reading(pages):
        first = pages[0]
        changed = replace(first.page.rows[0], raw=23)
        page = replace(first.page, rows=(changed, *first.page.rows[1:]))
        return (replace(first, page=page), *pages[1:])

    def test_v3_missing_tail(self):
        pages = self.collect()
        self.assertTrue(self.station.jobs.get('job').complete)
        with self.assertRaises(IncompleteEvidence):
            self.station.admission.admit('job', pages[:-1])
        self.assertIsNone(self.station.batches.find_by_task('job'))
        admitted = self.station.admission.admit('job', pages)
        self.assertEqual(len(admitted.batch.results), 3)
        self.assertEqual(admitted.pages, pages)

    def test_v3_mixed_release(self):
        pages = self.collect()
        self.portal.catalog.publish(self.column, 'r2', self.rows)
        newer = self.collect('job2', release='r2')
        with self.assertRaises(WrongFixedRelease):
            self.station.admission.admit('job', (pages[0], newer[1]))
        self.assertIsNone(self.station.batches.find_by_task('job'))
        self.portal.close()
        receipt = self.station.admission.admit('job', pages)
        self.assertEqual(receipt.batch.release_id, 'r1')
        self.assertEqual(receipt.pages, pages)

    def test_v3_original_page_and_chain(self):
        pages = self.collect()
        with self.assertRaises(OriginalPageMismatch):
            self.station.admission.admit('job', self.changed_reading(pages))
        self.assertIsNone(self.station.batches.find_by_task('job'))
        wrong_tail = replace(pages[1], page=replace(pages[1].page, request_cursor=None))
        with self.assertRaises(InvalidPageChain):
            self.station.admission.admit('job', (pages[0], wrong_tail))
        self.assertIsNone(self.station.batches.find_by_task('job'))
        with self.assertRaises(UnknownTask):
            self.station.admission.admit('unknown', pages)
        capture = self.station.capture_from(self.portal)
        capture.start_fixed('waiting', self.column, 'r1', 'p1')
        with self.assertRaises(IncompleteEvidence):
            self.station.admission.admit('waiting', pages)
        self.assertEqual(self.station.admission.admit('job', pages).pages, pages)

    def test_v4_revision_binding_exact_value_and_strict_limit(self):
        capture = self.station.capture_from(self.portal)
        capture.start_fixed('frozen', self.column, 'r1', 'p1')
        original = self.station.profiles.get('p1')
        with self.assertRaises(InvalidProfile):
            self.station.profiles.set_profile('bad', 0, 1, 4)
        with self.assertRaises(ProfileConflict):
            self.station.profiles.set_profile('p1', 2, 0, 9)
        self.assertEqual(self.station.profiles.set_profile('p1', Fraction(6, 4), 1, 4), original)
        self.station.profiles.set_profile('p2', 2, 0, 9)
        admitted = self.station.admission.admit('frozen', self.collect('frozen'))
        batch = self.station.batches.require(admitted.batch.batch_id)
        self.assertEqual(batch.profile, original)
        self.assertEqual((batch.profile.revision, batch.profile.scale, batch.profile.zero, batch.profile.limit),
                         ('p1', Fraction(3, 2), 1, Fraction(4)))
        self.assertEqual([row.micrometres for row in batch.results], [Fraction(4), Fraction(11, 2), Fraction(1)])
        self.assertEqual([row.over_limit for row in batch.results], [False, True, False])
        report = self.station.signer.sign(batch.batch_id)
        self.assertEqual([item.reading.source.point_id for item in report.details], ['B'])
        self.assertEqual(report.over_limit_ratio, Fraction(1, 3))

    def test_signed_readings_and_negative_fractional_limit(self):
        self.portal.catalog.publish(self.column, 'signed', (SourceRow('S', -2, -3, 'S-1'),))
        self.station.profiles.set_profile('signed', Fraction(1, 3), 0, Fraction(-5, 4))
        pages = self.collect('signed', release='signed', revision='signed')
        receipt = self.station.admission.admit('signed', pages)
        batch = self.station.batches.require(receipt.batch.batch_id)
        self.assertEqual(batch.results[0].source.raw, -3)
        self.assertEqual(batch.results[0].micrometres, Fraction(-1))
        self.assertTrue(batch.results[0].over_limit)

    def test_v5_atomic_visibility(self):
        pages = self.collect()
        connection = self.station.connection
        # Insert a deferred violation only on archive insert. The real COMMIT must reject it.
        connection.executescript('''
            CREATE TABLE test_parent (id INTEGER PRIMARY KEY);
            CREATE TABLE test_child (
                id INTEGER REFERENCES test_parent(id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER fail_archive_commit AFTER INSERT ON archived_pages
            BEGIN
                INSERT INTO test_child (id) VALUES (NEW.batch_id);
            END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
            self.station.admission.admit('job', pages)
        self.assertFalse(connection.in_transaction)
        with closing(open_station(self.station_path)) as observer:
            self.assertIsNone(observer.batches.find_by_task('job'))
            with self.assertRaises(UnknownBatch):
                observer.batches.require(1)
            for table in ('batches', 'batch_readings', 'archived_pages', 'row_origins', 'test_child'):
                with self.subTest(table=table):
                    self.assertEqual(observer.connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone(), (0,))
            self.assertEqual(observer.evidence.read('job'), pages)
            self.assertTrue(observer.jobs.get('job').complete)
        connection.execute('DROP TRIGGER fail_archive_commit')
        receipt = self.station.admission.admit('job', pages)
        self.assertEqual(self.station.admission.admit('job', pages), receipt)
        with closing(open_station(self.station_path)) as observer:
            self.assertEqual(observer.batches.find_by_task('job'), receipt.batch)
            self.assertEqual(observer.provenance.read(receipt.batch.batch_id), (pages, receipt.origins))
            self.assertEqual(observer.connection.execute('SELECT COUNT(*) FROM batches').fetchone(), (1,))
            self.assertEqual(observer.connection.execute('SELECT COUNT(*) FROM batch_readings').fetchone(), (3,))
            self.assertEqual(observer.connection.execute('SELECT COUNT(*) FROM archived_pages').fetchone(), (2,))
            self.assertEqual(observer.connection.execute('SELECT COUNT(*) FROM row_origins').fetchone(), (3,))

    def test_v5_replay_conflict(self):
        pages = self.collect()
        original = self.station.admission.admit('job', pages)
        self.assertEqual(self.station.admission.admit('job', list(pages)), original)
        self.assertEqual(self.station.admission.admit('job', pages), original)
        with self.assertRaises(SubmissionConflict):
            self.station.admission.admit('job', self.changed_reading(pages))
        self.assertEqual(self.station.batches.find_by_task('job'), original.batch)
        self.assertEqual(self.station.provenance.read(original.batch.batch_id), (original.pages, original.origins))
        self.assertEqual(self.station.connection.execute('SELECT COUNT(*) FROM batches').fetchone(), (1,))
