import io
from contextlib import redirect_stderr
from dataclasses import replace
from fractions import Fraction

from archive.batches import UnknownBatch
from handover.cli import main
from handover.reports import UnknownReport
from tests import StationCase


class HandoverTests(StationCase):
    def test_v6_sign_replay_and_offline_origin(self):
        contrast_rows = tuple(replace(row, source_version=f'{row.point_id}-prior') for row in self.rows)
        self.portal.catalog.publish(self.column, 'prior', contrast_rows)
        prior = self.station.admission.admit('prior', self.collect('prior', release='prior'))
        target = self.station.admission.admit('job', self.collect())
        self.assertEqual(prior.pages[0].sequence, target.pages[0].sequence)
        report = self.station.signer.sign(target.batch.batch_id)
        self.assertEqual(self.station.signer.sign(target.batch.batch_id), report)
        self.assertEqual(report.over_limit_ratio, Fraction(1, 3))
        self.assertEqual([detail.reading.source.point_id for detail in report.details], ['B'])
        self.assertEqual(self.station.connection.execute('SELECT COUNT(*) FROM reports').fetchone(), (1,))

        self.portal.close()
        self.station.close()
        self.reopen_station()
        receipt = self.station.reader.lookup(report.report_id)
        self.assertEqual(receipt.report, report)
        self.assertEqual(receipt.pages, target.pages)
        self.assertEqual(receipt.batch, target.batch)
        self.assertEqual([item.micrometres for item in receipt.batch.results],
                         [Fraction(4), Fraction(11, 2), Fraction(1)])
        self.assertEqual([(origin.point_id, origin.source_version, origin.page_sequence, origin.row_index)
                          for origin in receipt.origins], [('A', 'A-1', 1, 0), ('B', 'B-1', 1, 1), ('C', 'C-1', 2, 0)])
        pages = {item.sequence: item.page for item in receipt.pages}
        for origin, source in zip(receipt.origins, self.rows, strict=True):
            self.assertEqual(pages[origin.page_sequence].rows[origin.row_index], source)
        self.assertEqual(receipt.report.details[0].origin, receipt.origins[1])
        with self.assertRaises(UnknownReport):
            self.station.reader.lookup(report.report_id + 100)

    def test_v6_reopen_init_preserves_user_data(self):
        batch = self.station.admission.admit('job', self.collect()).batch
        report = self.station.signer.sign(batch.batch_id)
        original = self.station.reader.lookup(report.report_id)
        custom = self.station.profiles.set_profile('site-adjustment', Fraction(9, 8), -2, Fraction(7, 6))
        capture = self.station.capture_from(self.portal, page_length=1)
        capture.start_fixed('user-task', self.column, 'r1', custom.revision)
        capture.pull('user-task')
        checkpoint = self.station.jobs.get('user-task')
        partial_pages = self.station.evidence.read('user-task')
        self.portal.close()
        self.station.close()
        self.reopen_station()
        self.station.initialize()
        self.assertEqual(self.station.profiles.get(custom.revision), custom)
        self.assertEqual(self.station.jobs.get('user-task'), checkpoint)
        self.assertEqual(self.station.evidence.read('user-task'), partial_pages)
        self.assertEqual(self.station.reader.lookup(report.report_id), original)
        self.assertEqual(self.station.signer.sign(batch.batch_id), report)

    def test_v7_unknown_batch_has_no_report_and_cli_fails(self):
        with self.assertRaises(UnknownBatch):
            self.station.signer.sign(999)
        errors = io.StringIO()
        with redirect_stderr(errors):
            status = main(['--station', str(self.station_path), 'sign', '999'])
        self.assertEqual(status, 1)
        self.assertIn('unknown batch 999', errors.getvalue())
        self.assertEqual(self.station.connection.execute('SELECT COUNT(*) FROM reports').fetchone(), (0,))
        with self.assertRaises(UnknownReport):
            self.station.reader.lookup(1)

    def test_v8_empty_receipt_distinct_from_all_clear(self):
        self.portal.catalog.publish(self.column, 'clear', (self.rows[0],))
        self.portal.catalog.publish(self.column, 'empty', ())
        clear = self.station.admission.admit('clear', self.collect('clear', release='clear'))
        clear_report = self.station.signer.sign(clear.batch.batch_id)
        empty_pages = self.collect('empty', release='empty')
        self.assertEqual(len(empty_pages), 1)
        self.assertTrue(empty_pages[0].page.last)
        self.assertIsNone(empty_pages[0].page.request_cursor)
        self.assertIsNone(empty_pages[0].page.next_cursor)
        empty = self.station.admission.admit('empty', empty_pages)
        empty_report = self.station.signer.sign(empty.batch.batch_id)
        self.assertEqual(self.station.signer.sign(empty.batch.batch_id), empty_report)
        self.portal.close()
        self.station.close()
        self.reopen_station()

        received_clear = self.station.reader.lookup(clear_report.report_id)
        received_empty = self.station.reader.lookup(empty_report.report_id)
        self.assertEqual(received_clear.report.over_limit_ratio, Fraction(0))
        self.assertEqual(len(received_clear.batch.results), 1)
        self.assertEqual(received_clear.report.details, ())
        self.assertIsNone(received_empty.report.over_limit_ratio)
        self.assertEqual(received_empty.report.details, ())
        self.assertEqual(received_empty.batch.results, ())
        self.assertEqual(received_empty.origins, ())
        self.assertEqual(received_empty.pages, empty_pages)
        self.assertEqual(received_empty.pages[0].page.release_id, 'empty')
        self.assertEqual(received_empty.pages[0].page.rows, ())
        self.assertTrue(received_empty.pages[0].page.last)
