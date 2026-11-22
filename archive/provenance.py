import sqlite3
from dataclasses import dataclass

from archive.submissions import iter_located_rows
from capture.evidence import EvidencePage, decode_fixed_page, encode_fixed_page


@dataclass(frozen=True, slots=True)
class RowOrigin:
    point_id: str
    source_version: str
    page_sequence: int
    row_index: int


class BatchProvenance:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def initialize(self) -> None:
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS archived_pages (
                batch_id INTEGER NOT NULL REFERENCES batches(batch_id),
                page_sequence INTEGER NOT NULL CHECK (page_sequence > 0),
                payload TEXT NOT NULL,
                PRIMARY KEY (batch_id, page_sequence)
            );
            CREATE TABLE IF NOT EXISTS row_origins (
                batch_id INTEGER NOT NULL,
                point_id TEXT NOT NULL,
                source_version TEXT NOT NULL,
                page_sequence INTEGER NOT NULL,
                row_index INTEGER NOT NULL CHECK (row_index >= 0),
                PRIMARY KEY (batch_id, point_id),
                UNIQUE (batch_id, page_sequence, row_index),
                FOREIGN KEY (batch_id, page_sequence) REFERENCES archived_pages(batch_id, page_sequence)
            );
        ''')

    def store(self, batch_id: int, pages: tuple[EvidencePage, ...]) -> tuple[RowOrigin, ...]:
        self.connection.executemany('''
            INSERT INTO archived_pages (batch_id, page_sequence, payload) VALUES (?, ?, ?)
        ''', ((batch_id, item.sequence, encode_fixed_page(item.page)) for item in pages))
        origins = tuple(RowOrigin(row.point_id, row.source_version, sequence, index)
                        for sequence, index, row in iter_located_rows(pages))
        self.connection.executemany('''
            INSERT INTO row_origins (batch_id, point_id, source_version, page_sequence, row_index)
            VALUES (?, ?, ?, ?, ?)
        ''', ((batch_id, origin.point_id, origin.source_version, origin.page_sequence, origin.row_index)
              for origin in origins))
        return origins

    def read(self, batch_id: int) -> tuple[tuple[EvidencePage, ...], tuple[RowOrigin, ...]]:
        originals = self.connection.execute('''
            SELECT page_sequence, payload FROM archived_pages WHERE batch_id = ? ORDER BY page_sequence
        ''', (batch_id,))
        pages = tuple(EvidencePage(sequence, decode_fixed_page(payload)) for sequence, payload in originals)
        origins = self.connection.execute('''
            SELECT point_id, source_version, page_sequence, row_index FROM row_origins
            WHERE batch_id = ? ORDER BY page_sequence, row_index
        ''', (batch_id,))
        return pages, tuple(RowOrigin(*record) for record in origins)
