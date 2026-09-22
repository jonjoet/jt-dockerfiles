import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from support import PreservedTestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import plasmidsaurus_autofetch as fetch


class IgnoredOrderTests(PreservedTestCase):
    def setUp(self):
        super().setUp()
        self.data = self.root / 'data'
        self.scratch = self.root / 'scratch'
        self.data.mkdir()
        self.scratch.mkdir()
        self.item = {'code': 'IGNORED', 'status': 'complete'}
        self.folder = self.data / self.item['code']
        self.folder.mkdir()

    def manifest(self, days=0, layout=2):
        return json.dumps({
            'layout_version': layout, 'files': {}, 'item_code': 'IGNORED',
            'fetched_at': (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(),
        })

    def snapshot(self):
        return {
            str(path.relative_to(self.folder)): (
                path.read_bytes() if path.is_file() else None,
                path.stat().st_mtime_ns,
            ) for path in [self.folder, *self.folder.rglob('*')]
        }

    def test_ignore_precedes_all_order_states_without_logs_or_mutations(self):
        states = {
            'new': {},
            'complete': {'.complete': self.manifest()},
            'redundant-journal': {'.complete': self.manifest(60), '.refresh.json': 'bad'},
            'recovery': {'.refresh.json': self.manifest(60)},
            'invalid-complete': {'.complete': 'bad'},
            'invalid-journal': {'.refresh.json': 'bad'},
            'legacy': {'.complete': self.manifest(layout=1)},
        }
        for name, markers in states.items():
            with self.subTest(state=name):
                self.folder = self.data / name
                self.folder.mkdir()
                item = {'code': name, 'status': 'complete'}
                (self.folder / '.ignore').touch()
                (self.folder / '.reads.partial').mkdir()
                (self.folder / '.reads.partial/unfinished').write_bytes(b'keep staging')
                (self.folder / 'results').mkdir()
                (self.folder / 'results/local.fasta').write_bytes(b'keep data')
                for marker, content in markers.items():
                    (self.folder / marker).write_text(content)
                before = self.snapshot()
                budget = fetch.DownloadBudget(5)
                with mock.patch.object(fetch, 'load_manifest', side_effect=AssertionError('manifest read')), \
                     mock.patch.object(fetch, 'fetch_link') as links, \
                     mock.patch.object(fetch, 'download_to_scratch') as downloads, \
                     mock.patch.object(fetch, 'log') as logger:
                    # Restrict the scan to this order; every state must bypass
                    # manifest reads as well as the per-order network paths.
                    with mock.patch.object(Path, 'iterdir', return_value=iter([self.folder])):
                        self.assertEqual(fetch.select_work([item], None, self.data, 45), ([], []))
                    for dry_run in (False, True):
                        self.assertEqual(fetch.process_item(
                            item, 'token', self.data, self.scratch, 0, dry_run,
                            budget=budget,
                        ), 'skip-ignored')
                    links.assert_not_called()
                    downloads.assert_not_called()
                    self.assertEqual(logger.mock_calls, [])
                self.assertEqual(budget.orders, set())
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(list(self.scratch.iterdir()), [])

    def test_removing_marker_restores_normal_window_and_recovery_rules(self):
        marker = self.folder / '.ignore'
        marker.touch()
        self.assertEqual(fetch.select_work([self.item], None, self.data, 45), ([], []))
        marker.unlink()
        self.assertEqual(fetch.select_work([self.item], None, self.data, 45), ([self.item], []))
        complete = self.folder / '.complete'
        complete.write_text(self.manifest())
        marker.touch()
        self.assertEqual(fetch.select_work([self.item], None, self.data, 45), ([], []))
        marker.unlink()
        self.assertEqual(fetch.select_work([self.item], None, self.data, 45), ([], [self.item]))
        complete.write_text(self.manifest(60))
        marker.touch()
        marker.unlink()
        self.assertEqual(fetch.select_work([self.item], None, self.data, 45), ([], []))
        complete.rename(self.folder / '.refresh.json')
        marker.touch()
        self.assertEqual(fetch.select_work([self.item], None, self.data, 0), ([], []))
        marker.unlink()
        self.assertEqual(fetch.select_work([self.item], None, self.data, 0), ([], [self.item]))

    def test_queued_ignored_order_does_not_fail_run_or_block_other_orders(self):
        (self.folder / '.ignore').touch()
        (self.folder / '.refresh.json').write_text('invalid recovery journal')
        before = self.snapshot()
        (self.data / fetch.QUEUE_FILE).write_text(json.dumps({'orders': ['IGNORED', 'HEALTHY']}))
        healthy = {'code': 'HEALTHY', 'status': 'complete'}
        with mock.patch.dict(os.environ, {'PLASMIDSAURUS_CLIENT_ID': 'test',
                                          'PLASMIDSAURUS_CLIENT_SECRET': 'test'}), \
             mock.patch.object(sys, 'argv', ['autofetch', '--data-dir', str(self.data),
                                             '--scratch-dir', str(self.scratch)]), \
             mock.patch.object(fetch, 'setup_logging'), \
             mock.patch.object(fetch, 'get_access_token', return_value='token'), \
             mock.patch.object(fetch, 'get_items', return_value=[self.item, healthy]), \
             mock.patch.object(fetch, 'fetch_link', return_value=None) as links, \
             mock.patch.object(fetch, 'log') as logger:
            self.assertEqual(fetch.main(), 0)
            self.assertEqual(links.call_args_list, [
                mock.call('token', 'HEALTHY', 'results'),
                mock.call('token', 'HEALTHY', 'reads'),
            ])
            logger.warning.assert_not_called()
            logger.error.assert_not_called()
            logger.exception.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertTrue((self.data / 'HEALTHY/.complete').is_file())
        self.assertEqual(json.loads((self.data / fetch.QUEUE_FILE).read_text()), {'orders': ['HEALTHY']})
