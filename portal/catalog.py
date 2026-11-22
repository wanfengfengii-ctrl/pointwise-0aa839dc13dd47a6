import json
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict

from portal.releases import Release, build_release, validate_release_key
from portal.rows import SourceRow


class UnknownRelease(LookupError):
    pass


class ReleaseConflict(ValueError):
    pass


class Catalog:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS releases (
                column_name TEXT NOT NULL,
                release_id TEXT NOT NULL,
                source_rows TEXT NOT NULL,
                PRIMARY KEY (column_name, release_id)
            )
        ''')

    def _payload(self, column: str, release_id: str) -> str | None:
        row = self.connection.execute(
            'SELECT source_rows FROM releases WHERE column_name = ? AND release_id = ?',
            (column, release_id),
        ).fetchone()
        return None if row is None else row[0]

    def publish(self, column: str, release_id: str, rows: Iterable[SourceRow]) -> Release:
        release = build_release(column, release_id, rows)
        payload = json.dumps([asdict(row) for row in release.rows], separators=(',', ':'))
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            previous = self._payload(column, release_id)
            if previous is None:
                self.connection.execute(
                    'INSERT INTO releases (column_name, release_id, source_rows) VALUES (?, ?, ?)',
                    (column, release_id, payload),
                )
            elif previous != payload:
                raise ReleaseConflict(f'conflicting release {column!r}/{release_id!r}')
        return release

    def require_release(self, column: str, release_id: str) -> Release:
        validate_release_key(column, release_id)
        payload = self._payload(column, release_id)
        if payload is None:
            raise UnknownRelease(f'unknown release {column!r}/{release_id!r}')
        return Release(column, release_id, tuple(SourceRow(**row) for row in json.loads(payload)))
