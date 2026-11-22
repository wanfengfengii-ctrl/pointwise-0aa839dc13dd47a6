import json
import unittest
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from handover.station import open_portal, open_station
from portal.rows import SourceRow


class StationCase(unittest.TestCase):
    def setUp(self) -> None:
        workspace = TemporaryDirectory(prefix='bridge-regression-')
        self.addCleanup(workspace.cleanup)
        self.portal_path = Path(workspace.name) / 'portal.sqlite'
        self.station_path = Path(workspace.name) / 'station.sqlite'
        self.portal = open_portal(self.portal_path)
        self.addCleanup(self.portal.close)
        self.reopen_station()
        sample = Path(__file__).resolve().parent.parent / 'samples' / 'north_river.json'
        data = json.loads(sample.read_text(encoding='utf-8'))
        self.column = data['column']
        self.rows = tuple(SourceRow(**record) for record in data['rows'])
        self.portal.catalog.publish(self.column, 'r1', self.rows)
        self.station.profiles.set_profile('p1', Fraction(3, 2), 1, 4)

    def reopen_station(self) -> None:
        self.station = open_station(self.station_path)
        self.addCleanup(self.station.close)

    def collect(self, task_id: str = 'job', *, release: str = 'r1', revision: str = 'p1', length: int = 2):
        capture = self.station.capture_from(self.portal, page_length=length)
        capture.start_fixed(task_id, self.column, release, revision)
        progress = capture.pull(task_id)
        while not progress.complete:
            progress = capture.pull(task_id)
        return capture.evidence_for(task_id)
