import sqlite3
from dataclasses import dataclass, field

from capture.zones import ZoneRange, decode_zones, encode_zones, normalize_zones
from portal.catalog import Catalog
from portal.pages import validate_page_length
from quality.profiles import ProfileStore


class UnknownTask(LookupError):
    pass


class TaskConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FixedJob:
    task_id: str
    column: str
    release_id: str
    profile_revision: str
    page_length: int
    pages_read: int
    next_cursor: str | None
    complete: bool
    zones: tuple[ZoneRange, ...] | None = field(default=None)


class FixedJobs:
    def __init__(self, connection: sqlite3.Connection, profiles: ProfileStore) -> None:
        self.connection = connection
        self.profiles = profiles

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS fixed_jobs (
                task_id TEXT PRIMARY KEY NOT NULL,
                column_name TEXT NOT NULL,
                release_id TEXT NOT NULL,
                profile_revision TEXT NOT NULL REFERENCES profiles(revision),
                page_length TEXT NOT NULL,
                pages_read INTEGER NOT NULL DEFAULT 0,
                next_cursor TEXT,
                complete INTEGER NOT NULL DEFAULT 0 CHECK (complete IN (0, 1)),
                zones_payload TEXT
            )
        ''')
        columns = {record[1] for record in self.connection.execute('PRAGMA table_info(fixed_jobs)')}
        if 'zones_payload' not in columns:
            self.connection.execute('ALTER TABLE fixed_jobs ADD COLUMN zones_payload TEXT')

    def _find(self, task_id: str) -> FixedJob | None:
        row = self.connection.execute('''
            SELECT column_name, release_id, profile_revision, page_length, pages_read,
                   next_cursor, complete, zones_payload
            FROM fixed_jobs WHERE task_id = ?
        ''', (task_id,)).fetchone()
        if row is None:
            return None
        column, release_id, revision, length, pages, cursor, complete, zones_payload = row
        return FixedJob(task_id, column, release_id, revision, int(length), pages, cursor,
                        bool(complete), decode_zones(zones_payload))

    def start_fixed(self, task_id: str, column: str, release_id: str, revision: str, *,
                    catalog: Catalog, page_length: int,
                    zones: dict[str, tuple[int, int]] | None = None) -> FixedJob:
        if not isinstance(task_id, str) or not task_id:
            raise ValueError('task ID must be nonempty text')
        validate_page_length(page_length)
        zone_ranges = normalize_zones(zones)
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            previous = self._find(task_id)
            if previous is not None:
                if (column, release_id, revision) != (previous.column, previous.release_id, previous.profile_revision):
                    raise TaskConflict(f'conflicting task {task_id!r}')
                if zone_ranges is not None and zone_ranges != previous.zones:
                    raise TaskConflict(f'conflicting zone ranges for task {task_id!r}')
                return previous
            catalog.require_release(column, release_id)
            self.profiles.get(revision)
            self.connection.execute('''
                INSERT INTO fixed_jobs (task_id, column_name, release_id, profile_revision,
                                        page_length, zones_payload)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (task_id, column, release_id, revision, str(page_length),
                  encode_zones(zone_ranges)))
            return FixedJob(task_id, column, release_id, revision, page_length, 0, None,
                            False, zone_ranges)

    def get(self, task_id: str) -> FixedJob:
        if not isinstance(task_id, str) or not task_id:
            raise UnknownTask(f'unknown task {task_id!r}')
        job = self._find(task_id)
        if job is None:
            raise UnknownTask(f'unknown task {task_id!r}')
        return job
