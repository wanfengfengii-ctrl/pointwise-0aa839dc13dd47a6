import json
import sqlite3
from dataclasses import dataclass
from fractions import Fraction


class UnknownProfile(LookupError):
    pass


class InvalidProfile(ValueError):
    pass


class ProfileConflict(ValueError):
    pass


def _exact_fraction(value: Fraction | int) -> Fraction:
    if type(value) is int or isinstance(value, Fraction):
        return Fraction(value)
    raise InvalidProfile('scale and limit require an integer or Fraction')


@dataclass(frozen=True, slots=True)
class ProfileRevision:
    revision: str
    scale: Fraction
    zero: int
    limit: Fraction

    def to_record(self) -> dict:
        return {
            'revision': self.revision,
            'scale': [self.scale.numerator, self.scale.denominator],
            'zero': self.zero,
            'limit': [self.limit.numerator, self.limit.denominator],
        }

    @classmethod
    def from_record(cls, record: dict) -> 'ProfileRevision':
        return cls(record['revision'], Fraction(*record['scale']), record['zero'], Fraction(*record['limit']))


class ProfileStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS profiles (
                revision TEXT PRIMARY KEY NOT NULL,
                parameters TEXT NOT NULL
            )
        ''')

    def _find(self, revision: str) -> ProfileRevision | None:
        row = self.connection.execute(
            'SELECT parameters FROM profiles WHERE revision = ?', (revision,),
        ).fetchone()
        return None if row is None else ProfileRevision.from_record(json.loads(row[0]))

    def set_profile(self, revision: str, scale: Fraction | int, zero: int,
                    limit: Fraction | int) -> ProfileRevision:
        if not isinstance(revision, str) or not revision:
            raise InvalidProfile('profile revision must be nonempty text')
        exact_scale = _exact_fraction(scale)
        if exact_scale <= 0 or type(zero) is not int:
            raise InvalidProfile('profile requires a positive scale and integer zero')
        profile = ProfileRevision(revision, exact_scale, zero, _exact_fraction(limit))
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            previous = self._find(revision)
            if previous is not None:
                if previous != profile:
                    raise ProfileConflict(f'conflicting profile {revision!r}')
                return previous
            self.connection.execute(
                'INSERT INTO profiles (revision, parameters) VALUES (?, ?)',
                (revision, json.dumps(profile.to_record())),
            )
        return profile

    def get(self, revision: str) -> ProfileRevision:
        if not isinstance(revision, str) or not revision:
            raise UnknownProfile(f'unknown profile {revision!r}')
        profile = self._find(revision)
        if profile is None:
            raise UnknownProfile(f'unknown profile {revision!r}')
        return profile
