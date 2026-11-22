import sqlite3
from pathlib import Path

from archive.admission import Admission
from archive.batches import BatchStore
from archive.provenance import BatchProvenance
from archive.transactions import BatchPublisher
from capture.checkpoints import CaptureCheckpoints
from capture.evidence import EvidenceLedger
from capture.jobs import FixedJobs
from capture.paging import FixedCapture
from handover.lookup import ReportLookup
from handover.receipts import ReportSigner
from handover.reports import ReportStore
from portal.catalog import Catalog
from portal.pages import FixedPortal
from quality.profiles import ProfileStore


class Station:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.profiles = ProfileStore(connection)
        self.jobs = FixedJobs(connection, self.profiles)
        self.evidence = EvidenceLedger(connection)
        self.checkpoints = CaptureCheckpoints(connection, self.jobs, self.evidence)
        self.batches = BatchStore(connection)
        self.provenance = BatchProvenance(connection)
        self.reports = ReportStore(connection)
        publisher = BatchPublisher(connection, self.batches, self.provenance)
        self.admission = Admission(self.jobs, self.evidence, self.profiles, publisher)
        self.signer = ReportSigner(connection, self.batches, self.provenance, self.reports)
        self.reader = ReportLookup(self.reports, self.batches, self.provenance)

    def initialize(self) -> None:
        self.profiles.initialize()
        self.jobs.initialize()
        self.evidence.initialize()
        self.batches.initialize()
        self.provenance.initialize()
        self.reports.initialize()

    def capture_from(self, portal: FixedPortal, *, page_length: int = 2) -> FixedCapture:
        return FixedCapture(portal, self.jobs, self.evidence, self.checkpoints, page_length)

    def close(self) -> None:
        self.connection.close()


def _connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        connection.close()
        raise
    return connection


def open_station(path: str | Path) -> Station:
    connection = _connect(path)
    try:
        station = Station(connection)
        station.initialize()
    except BaseException:
        connection.close()
        raise
    return station


def open_portal(path: str | Path) -> FixedPortal:
    connection = _connect(path)
    try:
        catalog = Catalog(connection)
        catalog.initialize()
    except BaseException:
        connection.close()
        raise
    return FixedPortal(catalog)
