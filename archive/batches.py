import json
import sqlite3
from dataclasses import dataclass

from quality.profiles import ProfileRevision
from quality.results import ReadingResult


class UnknownBatch(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class Batch:
    batch_id: int
    task_id: str
    column: str
    release_id: str
    profile: ProfileRevision
    results: tuple[ReadingResult, ...]


class BatchStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def initialize(self) -> None:
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS batches (
                batch_id INTEGER PRIMARY KEY,
                task_id TEXT NOT NULL UNIQUE REFERENCES fixed_jobs(task_id),
                column_name TEXT NOT NULL,
                release_id TEXT NOT NULL,
                frozen_profile TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS batch_readings (
                batch_id INTEGER NOT NULL REFERENCES batches(batch_id),
                ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
                result TEXT NOT NULL,
                PRIMARY KEY (batch_id, ordinal)
            );
        ''')

    def insert(self, task_id: str, column: str, release_id: str, profile: ProfileRevision,
               results: tuple[ReadingResult, ...]) -> Batch:
        cursor = self.connection.execute('''
            INSERT INTO batches (task_id, column_name, release_id, frozen_profile) VALUES (?, ?, ?, ?)
        ''', (task_id, column, release_id, json.dumps(profile.to_record())))
        batch_id = cursor.lastrowid
        self.connection.executemany('''
            INSERT INTO batch_readings (batch_id, ordinal, result) VALUES (?, ?, ?)
        ''', ((batch_id, ordinal, json.dumps(result.to_record())) for ordinal, result in enumerate(results)))
        return Batch(batch_id, task_id, column, release_id, profile, results)

    def _assemble(self, row: tuple) -> Batch:
        batch_id, task_id, column, release_id, parameters = row
        result_rows = self.connection.execute('''
            SELECT result FROM batch_readings WHERE batch_id = ? ORDER BY ordinal
        ''', (batch_id,))
        results = tuple(ReadingResult.from_record(json.loads(payload)) for (payload,) in result_rows)
        return Batch(batch_id, task_id, column, release_id,
                     ProfileRevision.from_record(json.loads(parameters)), results)

    def find_by_task(self, task_id: str) -> Batch | None:
        row = self.connection.execute('''
            SELECT batch_id, task_id, column_name, release_id, frozen_profile FROM batches WHERE task_id = ?
        ''', (task_id,)).fetchone()
        return None if row is None else self._assemble(row)

    def require(self, batch_id: int) -> Batch:
        if type(batch_id) is not int or not 0 < batch_id < 2**63:
            raise UnknownBatch(f'unknown batch {batch_id!r}')
        row = self.connection.execute('''
            SELECT batch_id, task_id, column_name, release_id, frozen_profile FROM batches WHERE batch_id = ?
        ''', (batch_id,)).fetchone()
        if row is None:
            raise UnknownBatch(f'unknown batch {batch_id}')
        return self._assemble(row)
