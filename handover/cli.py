import argparse
import json
import sqlite3
import sys
from contextlib import ExitStack, closing
from dataclasses import asdict, is_dataclass
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from capture.evidence import EvidencePage, decode_fixed_page
from handover.lookup import ReportReceipt
from handover.station import open_portal, open_station
from portal.rows import SourceRow


def _read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _read_array(path: Path) -> list:
    data = _read_json(path)
    if not isinstance(data, list):
        raise ValueError('input file must contain a JSON array')
    return data


def _json_value(value):
    if isinstance(value, Fraction):
        return str(value)
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f'{type(value).__name__} cannot be represented as JSON')


def run_shift_demo() -> ReportReceipt:
    sample_path = Path(__file__).resolve().parent.parent / 'samples' / 'north_river.json'
    sample = _read_json(sample_path)
    rows = tuple(SourceRow(**record) for record in sample['rows'])
    profile = sample['profile']
    with TemporaryDirectory(prefix='bridge-shift-') as directory:
        portal_path = Path(directory) / 'portal.sqlite'
        station_path = Path(directory) / 'station.sqlite'
        with closing(open_portal(portal_path)) as portal, closing(open_station(station_path)) as station:
            portal.catalog.publish(sample['column'], sample['release_id'], rows)
            station.profiles.set_profile(profile['revision'], Fraction(profile['scale']),
                                         profile['zero'], Fraction(profile['limit']))
            capture = station.capture_from(portal, page_length=sample['page_length'])
            task_id = 'demo-shift'
            capture.start_fixed(task_id, sample['column'], sample['release_id'], profile['revision'])
            progress = capture.pull(task_id)
            while not progress.complete:
                progress = capture.pull(task_id)
            admitted = station.admission.admit(task_id, capture.evidence_for(task_id))
            signed = station.signer.sign(admitted.batch.batch_id)
        with closing(open_station(station_path)) as station:
            receipt = station.reader.lookup(signed.report_id)

    expected = {'values': ['4', '11/2', '1'], 'origins': [['A', 'A-1', 1, 0], ['B', 'B-1', 1, 1], ['C', 'C-1', 2, 0]]}
    actual = {
        'values': [str(result.micrometres) for result in receipt.batch.results],
        'origins': [[origin.point_id, origin.source_version, origin.page_sequence, origin.row_index]
                    for origin in receipt.origins],
    }
    downstream_expected = {'point_ids': ['B'], 'ratio': '1/3'}
    downstream_actual = {
        'point_ids': [detail.reading.source.point_id for detail in receipt.report.details],
        'ratio': str(receipt.report.over_limit_ratio),
    }
    by_page = {item.sequence: item.page for item in receipt.pages}
    recovered_rows = tuple(by_page[origin.page_sequence].rows[origin.row_index] for origin in receipt.origins)
    if (actual != expected or downstream_actual != downstream_expected or recovered_rows != rows
            or receipt.pages != admitted.pages or receipt.report != signed):
        raise ValueError('offline receipt differs from the signed shift and its source readings')
    scenario = {
        'case_id': 'V6',
        'input': sample,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': ['quality/conversion.py', 'archive/provenance.py', 'handover/selection.py', 'handover/lookup.py'],
        'oracle': '手算 2×3/2+1=4、3×3/2+1=11/2、0×3/2+1=1，严格大于 4 的仅 B。按两行一页手排来源位置。',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False))
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Bridge monitoring fixed-release station')
    parser.add_argument('--portal', type=Path, default=Path('portal.sqlite'))
    parser.add_argument('--station', type=Path, default=Path('station.sqlite'))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='initialize the portal and station stores')
    commands.add_parser('demo', help='run and receive a complete offline shift')

    publish = commands.add_parser('publish', help='publish a fixed release from a JSON row array')
    publish.add_argument('column')
    publish.add_argument('release')
    publish.add_argument('file', type=Path)
    page = commands.add_parser('page', help='read one portal page')
    page.add_argument('column')
    page.add_argument('release')
    page.add_argument('length', type=int)
    page.add_argument('--cursor')
    profile = commands.add_parser('profile', help='register a quality profile revision')
    profile.add_argument('revision')
    profile.add_argument('scale', type=Fraction)
    profile.add_argument('zero', type=int)
    profile.add_argument('limit', type=Fraction)
    start = commands.add_parser('start', help='register a fixed capture job')
    start.add_argument('task')
    start.add_argument('column')
    start.add_argument('release')
    start.add_argument('revision')
    start.add_argument('--page-length', type=int, default=2)
    pull = commands.add_parser('pull', help='capture the next page')
    pull.add_argument('task')
    evidence = commands.add_parser('evidence', help='export the captured page array')
    evidence.add_argument('task')
    admit = commands.add_parser('admit', help='admit an exported page array')
    admit.add_argument('task')
    admit.add_argument('file', type=Path)
    commands.add_parser('sign', help='sign a batch').add_argument('batch', type=int)
    commands.add_parser('lookup', help='receive a signed report offline').add_argument('report', type=int)
    return parser


def _execute(args: argparse.Namespace, resources: ExitStack):
    command = args.command
    if command == 'demo':
        return run_shift_demo()
    if command in {'init', 'publish', 'page', 'start', 'pull'}:
        portal = resources.enter_context(closing(open_portal(args.portal)))
        if command == 'publish':
            return portal.catalog.publish(args.column, args.release,
                                          (SourceRow(**record) for record in _read_array(args.file)))
        if command == 'page':
            return portal.page(args.column, args.release, args.cursor, args.length)

    station = resources.enter_context(closing(open_station(args.station)))
    if command == 'init':
        return {'portal': str(args.portal), 'station': str(args.station)}
    if command == 'profile':
        return station.profiles.set_profile(args.revision, args.scale, args.zero, args.limit)
    if command == 'start':
        capture = station.capture_from(portal, page_length=args.page_length)
        return capture.start_fixed(args.task, args.column, args.release, args.revision)
    if command == 'pull':
        return station.capture_from(portal).pull(args.task)
    if command == 'evidence':
        return station.evidence_for(args.task)
    if command == 'admit':
        pages = []
        for record in _read_array(args.file):
            if not isinstance(record, dict) or record.keys() != {'sequence', 'page'}:
                raise ValueError('each evidence entry requires sequence and page')
            pages.append(EvidencePage(record['sequence'], decode_fixed_page(json.dumps(record['page']))))
        return station.admission.admit(args.task, pages)
    if command == 'sign':
        return station.signer.sign(args.batch)
    if command == 'lookup':
        return station.reader.lookup(args.report)
    raise ValueError(f'unknown command {command!r}')


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        with ExitStack() as resources:
            result = _execute(args, resources)
        print(json.dumps(result, default=_json_value, ensure_ascii=False, sort_keys=True))
    except (LookupError, OSError, ValueError, TypeError, sqlite3.Error) as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
