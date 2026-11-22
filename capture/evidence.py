import json
import sqlite3
from dataclasses import asdict, dataclass

from portal.pages import FixedPage
from portal.rows import SourceRow


@dataclass(frozen=True, slots=True)
class EvidencePage:
    sequence: int
    page: FixedPage


def encode_fixed_page(page: FixedPage) -> str:
    return json.dumps(asdict(page), sort_keys=True, separators=(',', ':'))


def decode_fixed_page(payload: str) -> FixedPage:
    record = json.loads(payload)
    if not isinstance(record, dict) or not isinstance(record.get('rows'), list):
        raise ValueError('a fixed page requires an object with a row array')
    record['rows'] = tuple(SourceRow(**row) for row in record['rows'])
    return FixedPage(**record)


class EvidenceLedger:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS captured_pages (
                task_id TEXT NOT NULL REFERENCES fixed_jobs(task_id),
                page_sequence INTEGER NOT NULL CHECK (page_sequence > 0),
                payload TEXT NOT NULL,
                PRIMARY KEY (task_id, page_sequence)
            )
        ''')

    def append(self, task_id: str, evidence: EvidencePage) -> None:
        self.connection.execute('''
            INSERT INTO captured_pages (task_id, page_sequence, payload) VALUES (?, ?, ?)
        ''', (task_id, evidence.sequence, encode_fixed_page(evidence.page)))

    def read(self, task_id: str) -> tuple[EvidencePage, ...]:
        records = self.connection.execute('''
            SELECT page_sequence, payload FROM captured_pages WHERE task_id = ? ORDER BY page_sequence
        ''', (task_id,))
        return tuple(EvidencePage(sequence, decode_fixed_page(payload)) for sequence, payload in records)
