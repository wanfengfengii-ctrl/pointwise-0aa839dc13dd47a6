import io
import json
from contextlib import redirect_stderr

from handover.cli import _parse_zones, main
from portal.rows import SourceRow
from tests import StationCase


class ZoneCliTests(StationCase):
    def test_zone_argument_parser(self):
        self.assertIsNone(_parse_zones(None))
        self.assertEqual(_parse_zones('甲:10-20,乙:25-30'), {'甲': (10, 20), '乙': (25, 30)})
        for bad in ('甲', '甲:10', '甲:a-b', ',', ' :1-2'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _parse_zones(bad)

    def test_zoned_cli_round_trip(self):
        self.portal.catalog.publish(self.column, 'rz', (
            *self.rows, SourceRow('X', 45, 9, 'X-1'),
        ))
        base = ['--portal', str(self.portal_path), '--station', str(self.station_path)]
        status = main([*base, 'start', 'cli-zones', self.column, 'rz', 'p1',
                       '--zones', '甲:10-20,乙:25-30,丙:55-60'])
        self.assertEqual(status, 0)
        status = main([*base, 'pull', 'cli-zones'])
        while not self.station.jobs.get('cli-zones').complete:
            status = main([*base, 'pull', 'cli-zones'])
        self.assertEqual(status, 0)

        evidence_path = self.portal_path.parent / 'zone-evidence.json'
        buffer = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(main(['--station', str(self.station_path),
                                   'evidence', 'cli-zones']), 0)
        evidence_path.write_text(buffer.getvalue(), encoding='utf-8')
        package = json.loads(evidence_path.read_text(encoding='utf-8'))
        self.assertEqual(set(package), {'pages', 'coverage'})
        retained = [row['point_id'] for item in package['pages'] for row in item['page']['rows']]
        self.assertNotIn('X', retained)

        admit_buffer = io.StringIO()
        with contextlib.redirect_stdout(admit_buffer):
            self.assertEqual(main(['--station', str(self.station_path),
                                   'admit', 'cli-zones', str(evidence_path)]), 0)
        admitted = json.loads(admit_buffer.getvalue())
        self.assertEqual(set(admitted['zone_results']), {'甲', '乙', '丙'})

        sign_buffer = io.StringIO()
        with contextlib.redirect_stdout(sign_buffer):
            self.assertEqual(main(['--station', str(self.station_path),
                                   'sign', str(admitted['batch']['batch_id'])]), 0)
        report = json.loads(sign_buffer.getvalue())
        self.assertIsNone(report['over_limit_ratio'])
        self.assertEqual(report['zones']['丙'], {'details': [], 'over_limit_ratio': None, 'total_count': 0})
        self.assertEqual(report['zones']['甲']['over_limit_ratio'], '1/2')

        errors = io.StringIO()
        with redirect_stderr(errors):
            bad = main([*base, 'start', 'bad-zones', self.column, 'rz', 'p1', '--zones', '甲:20-10'])
        self.assertEqual(bad, 1)
        self.assertIn('InvalidZone', errors.getvalue())
