from contextlib import closing
from dataclasses import replace
from fractions import Fraction

from archive.submissions import OriginalPageMismatch
from capture.completeness import IncompleteEvidence, WrongFixedRelease
from capture.jobs import TaskConflict, UnknownTask
from capture.zones import (
    InvalidZone,
    MissingZoneProof,
    ZoneViolation,
    decode_zones,
    encode_zones,
    normalize_zones,
    verify_zone_pages,
    zone_proof,
)
from handover.station import open_portal, open_station
from portal.rows import SourceRow
from tests import StationCase


class ZoneCaptureTests(StationCase):
    def setUp(self) -> None:
        super().setUp()
        self.extra = (
            SourceRow('D', 40, 5, 'D-1'),
            SourceRow('X', 45, 9, 'X-1'),
            SourceRow('E', 50, 1, 'E-1'),
        )
        self.portal.catalog.publish(self.column, 'rz', (*self.rows, *self.extra))
        # 甲 [10,20]、乙 [20,40] 共享 B(20)；丙 [55,60] 真正无原读
        self.zones = {'甲': (10, 20), '乙': (20, 40), '丙': (55, 60)}

    def collect_zoned(self, task_id='zjob', zones=None, length=2):
        zones = self.zones if zones is None else zones
        capture = self.station.capture_from(self.portal, page_length=length)
        capture.start_fixed(task_id, self.column, 'rz', 'p1', zones=zones)
        progress = capture.pull(task_id)
        while not progress.complete:
            progress = capture.pull(task_id)
        return capture.evidence_for(task_id)

    def test_zones_normalization(self):
        self.assertIsNone(normalize_zones(None))
        with self.assertRaises(InvalidZone):
            normalize_zones({})
        with self.assertRaises(InvalidZone):
            normalize_zones({'甲': (1,)})
        with self.assertRaises(InvalidZone):
            normalize_zones({'甲': (20, 10)})
        with self.assertRaises(InvalidZone):
            normalize_zones({1: (10, 20)})
        normalized = normalize_zones(self.zones)
        self.assertEqual(decode_zones(encode_zones(normalized)), normalized)

    def test_start_fixed_zones_optional_and_reusable(self):
        capture = self.station.capture_from(self.portal)
        plain = capture.start_fixed('plain', self.column, 'r1', 'p1')
        self.assertIsNone(plain.zones)
        zoned = capture.start_fixed('zjob', self.column, 'rz', 'p1', zones=self.zones)
        self.assertEqual([zone.name for zone in zoned.zones], ['甲', '乙', '丙'])
        self.assertEqual(capture.start_fixed('zjob', self.column, 'rz', 'p1', zones=self.zones), zoned)
        with self.assertRaises(TaskConflict):
            capture.start_fixed('zjob', self.column, 'rz', 'p1', zones={'甲': (10, 10)})
        with self.assertRaises(UnknownTask):
            capture.pull('never-started')

    def test_union_filtering_dedup_and_terminal_proof(self):
        package = self.collect_zoned()
        self.assertEqual(set(package), {'pages', 'coverage'})
        flat = [row.point_id for item in package['pages'] for row in item.page.rows]
        # X=45 与 E=50 落在并集外，不得到站；B 为共享测点只保留一份
        self.assertEqual(flat, ['A', 'B', 'C', 'D'])
        self.assertEqual(flat.count('B'), 1)
        terminal = package['pages'][-1]
        self.assertTrue(terminal.page.last)
        self.assertEqual(terminal.page.rows, ())
        coverage = package['coverage']
        self.assertEqual(set(coverage), {'甲', '乙', '丙'})
        for name, zone in (('甲', (10, 20)), ('乙', (20, 40)), ('丙', (55, 60))):
            self.assertEqual(coverage[name]['release_id'], 'rz')
            self.assertEqual(coverage[name]['range'], list(zone))
            self.assertEqual(
                coverage[name]['proof'],
                zone_proof('rz', next(z for z in normalize_zones(self.zones) if z.name == name), terminal),
            )

    def test_incomplete_zoned_evidence(self):
        capture = self.station.capture_from(self.portal)
        capture.start_fixed('partial', self.column, 'rz', 'p1', zones=self.zones)
        capture.pull('partial')
        with self.assertRaises(IncompleteEvidence):
            capture.evidence_for('partial')

    def test_restart_keeps_zoned_progress(self):
        capture = self.station.capture_from(self.portal, page_length=1)
        capture.start_fixed('restart', self.column, 'rz', 'p1', zones=self.zones)
        capture.pull('restart')
        checkpoint = self.station.jobs.get('restart')
        evidence = self.station.evidence.read('restart')
        self.portal.close()
        self.station.close()
        self.reopen_station()
        self.portal = open_portal(self.portal_path)
        self.addCleanup(self.portal.close)
        capture = self.station.capture_from(self.portal, page_length=1)
        self.assertEqual(capture.start_fixed('restart', self.column, 'rz', 'p1', zones=self.zones), checkpoint)
        progress = capture.pull('restart')
        while not progress.complete:
            progress = capture.pull('restart')
        self.assertEqual(self.station.evidence.read('restart')[:1], evidence)
        self.assertEqual(self.station.jobs.get('restart').zones, checkpoint.zones)


class ZoneAdmissionTests(StationCase):
    def setUp(self) -> None:
        super().setUp()
        self.portal.catalog.publish(self.column, 'rz', (
            *self.rows,
            SourceRow('D', 40, 5, 'D-1'),
            SourceRow('X', 45, 9, 'X-1'),
        ))
        self.zones = {'甲': (10, 20), '乙': (20, 40), '丙': (55, 60)}

    def collect_zoned(self, task_id='zjob', zones=None):
        zones = self.zones if zones is None else zones
        capture = self.station.capture_from(self.portal, page_length=2)
        capture.start_fixed(task_id, self.column, 'rz', 'p1', zones=zones)
        progress = capture.pull(task_id)
        while not progress.complete:
            progress = capture.pull(task_id)
        return capture.evidence_for(task_id)

    def test_zoned_admission_reports_and_lookup(self):
        package = self.collect_zoned()
        admitted = self.station.admission.admit('zjob', package)
        self.assertEqual(set(admitted.zone_results), {'甲', '乙', '丙'})
        self.assertEqual([r.source.point_id for r in admitted.zone_results['甲']], ['A', 'B'])
        self.assertEqual([r.source.point_id for r in admitted.zone_results['乙']], ['B', 'C', 'D'])
        self.assertEqual(admitted.zone_results['丙'], ())
        # 共享测点 B 在两区各自计入，出处引用同一原页同一位置
        origin_b = next(o for o in admitted.origins if o.point_id == 'B')
        page = {item.sequence: item.page for item in admitted.pages}[origin_b.page_sequence]
        self.assertEqual(page.rows[origin_b.row_index].point_id, 'B')

        report = self.station.signer.sign(admitted.batch.batch_id)
        self.assertEqual(report.details, ())
        self.assertIsNone(report.over_limit_ratio)
        self.assertEqual(report.zones['甲'].total_count, 2)
        self.assertEqual([d.reading.source.point_id for d in report.zones['甲'].details], ['B'])
        self.assertEqual(report.zones['甲'].over_limit_ratio, Fraction(1, 2))
        self.assertEqual(report.zones['乙'].total_count, 3)
        self.assertEqual([d.reading.source.point_id for d in report.zones['乙'].details], ['B', 'D'])
        self.assertEqual(report.zones['乙'].over_limit_ratio, Fraction(2, 3))
        self.assertEqual(report.zones['丙'].total_count, 0)
        self.assertEqual(report.zones['丙'].details, ())
        self.assertIsNone(report.zones['丙'].over_limit_ratio)

        self.portal.close()
        self.station.close()
        self.reopen_station()
        receipt = self.station.reader.lookup(report.report_id)
        self.assertEqual(receipt.coverage, package['coverage'])
        self.assertEqual(receipt.report.zones, report.zones)
        # 领取的原页中仍无范围外测点
        received = [r.point_id for item in receipt.pages for r in item.page.rows]
        self.assertNotIn('X', received)

    def test_missing_and_forged_coverage_blocks_order(self):
        package = self.collect_zoned()
        with self.assertRaises(ValueError):
            self.station.admission.admit('zjob', {'pages': package['pages']})
        broken = {'pages': package['pages'], 'coverage': dict(package['coverage'])}
        del broken['coverage']['乙']
        with self.assertRaises(MissingZoneProof):
            self.station.admission.admit('zjob', broken)
        forged = {'pages': package['pages'], 'coverage': {
            name: dict(entry, proof='0' * 64) for name, entry in package['coverage'].items()
        }}
        with self.assertRaises(MissingZoneProof):
            self.station.admission.admit('zjob', forged)
        # 删换单区键后用同形数据复投即可成功
        broken['coverage']['乙'] = package['coverage']['乙']
        admitted = self.station.admission.admit('zjob', broken)
        self.assertEqual(self.station.batches.require(admitted.batch.batch_id).task_id, 'zjob')

    def test_wrong_release_out_of_zone_and_tamper_rejected_without_half_batch(self):
        package = self.collect_zoned()
        pages = package['pages']
        wrong_release = replace(pages[0], page=replace(pages[0].page, release_id='r9'))
        with self.assertRaises(WrongFixedRelease):
            self.station.admission.admit('zjob', {'pages': (wrong_release, *pages[1:]),
                                                  'coverage': package['coverage']})
        # 越权：直接构造通过链结构检查但落在授权并集外的件，逐区核定必须拒绝
        unauthorized_page = replace(pages[0].page,
                                    rows=(SourceRow('Z', 99, 7, 'Z-1'),), last=True, next_cursor=None)
        with self.assertRaises(ZoneViolation):
            verify_zone_pages((replace(pages[0], page=unauthorized_page),),
                              self.column, 'rz', normalize_zones(self.zones))
        # 篡改留存原件在准备阶段即被原页比对拒绝
        tampered = replace(pages[0].page,
                           rows=(replace(pages[0].page.rows[0], raw=99), *pages[0].page.rows[1:]))
        with self.assertRaises(OriginalPageMismatch):
            self.station.admission.admit('zjob', {'pages': (replace(pages[0], page=tampered), *pages[1:]),
                                                  'coverage': package['coverage']})
        self.assertIsNone(self.station.batches.find_by_task('zjob'))
        for table in ('batches', 'archived_pages', 'row_origins', 'zone_coverage', 'zone_readings'):
            with self.subTest(table=table):
                self.assertEqual(self.station.connection.execute(
                    f'SELECT COUNT(*) FROM {table}').fetchone(), (0,))
        # 拒收后原采集件可续办
        admitted = self.station.admission.admit('zjob', package)
        self.assertEqual(admitted.coverage, package['coverage'])

    def test_replay_and_conflict(self):
        package = self.collect_zoned()
        first = self.station.admission.admit('zjob', package)
        self.assertEqual(self.station.admission.admit('zjob', dict(package)), first)
        altered = replace(package['pages'][0].page,
                          rows=(replace(package['pages'][0].page.rows[0], raw=99),
                                *package['pages'][0].page.rows[1:]))
        conflict = {'pages': (replace(package['pages'][0], page=altered), *package['pages'][1:]),
                    'coverage': package['coverage']}
        with self.assertRaises(OriginalPageMismatch):
            self.station.admission.admit('zjob', conflict)
        self.assertEqual(self.station.batches.find_by_task('zjob'), first.batch)

    def test_legacy_package_rejected_for_zoned_task_and_vice_versa(self):
        package = self.collect_zoned('zjob')
        with self.assertRaises(ValueError):
            self.station.admission.admit('zjob', package['pages'])
        capture = self.station.capture_from(self.portal)
        capture.start_fixed('plain', self.column, 'r1', 'p1')
        progress = capture.pull('plain')
        while not progress.complete:
            progress = capture.pull('plain')
        plain_pages = self.station.evidence.read('plain')
        with self.assertRaises(ValueError):
            self.station.admission.admit('plain', {'pages': plain_pages, 'coverage': {}})
        # 旧整版入口仍按原结构工作
        receipt = self.station.admission.admit('plain', plain_pages)
        self.assertEqual(receipt.pages, plain_pages)

    def test_failed_commit_leaves_no_partial_zone_order(self):
        import sqlite3
        package = self.collect_zoned('zjob')
        connection = self.station.connection
        connection.executescript('''
            CREATE TABLE t_parent (id INTEGER PRIMARY KEY);
            CREATE TABLE t_child (
                id INTEGER REFERENCES t_parent(id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER fail_zone_commit AFTER INSERT ON zone_coverage
            BEGIN
                INSERT INTO t_child (id) VALUES (NEW.batch_id);
            END;
        ''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.station.admission.admit('zjob', package)
        self.assertFalse(connection.in_transaction)
        with closing(open_station(self.station_path)) as observer:
            self.assertIsNone(observer.batches.find_by_task('zjob'))
            for table in ('batches', 'archived_pages', 'zone_coverage', 'zone_readings'):
                self.assertEqual(observer.connection.execute(
                    f'SELECT COUNT(*) FROM {table}').fetchone(), (0,))
        connection.execute('DROP TRIGGER fail_zone_commit')
        admitted = self.station.admission.admit('zjob', package)
        self.assertEqual(admitted.zone_results['丙'], ())
