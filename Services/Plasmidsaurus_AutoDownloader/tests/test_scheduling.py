import json
import os
import sys
from pathlib import Path
from unittest import mock

from support import PreservedTestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import plasmidsaurus_autofetch as fetch


class SchedulingTests(PreservedTestCase):
    def setUp(self):
        super().setUp()
        self.pending = [{'code': 'NEW' + str(i)} for i in range(7)]
        self.rechecks = [{'code': 'OLD' + str(i)} for i in range(7)]
        self.processed = []
        self.downloaded = []
        self.unchanged = set()

    def run_main(self, dry_run=False, process=None):
        argv = ['autofetch', '--data-dir', str(self.root),
                '--scratch-dir', str(self.root / 'scratch')]
        if dry_run:
            argv.append('--dry-run')
        def record(item, *args, budget):
            code = item['code']
            self.processed.append(code)
            if dry_run:
                return 'would-fetch'
            if code in self.unchanged:
                return 'unchanged'
            try:
                budget.claim(code)
            except fetch.DownloadDeferred:
                return 'deferred'
            self.downloaded.append(code)
            return process(item) if process else 'done'
        with mock.patch.dict(os.environ, {'PLASMIDSAURUS_CLIENT_ID': 'test',
                                          'PLASMIDSAURUS_CLIENT_SECRET': 'test'}), \
             mock.patch.object(sys, 'argv', argv), \
             mock.patch.object(fetch, 'setup_logging'), \
             mock.patch.object(fetch, 'get_access_token', return_value='token'), \
             mock.patch.object(fetch, 'get_items', return_value=[]), \
             mock.patch.object(fetch, 'select_work', return_value=(self.pending, self.rechecks)), \
             mock.patch.object(fetch, 'process_item', side_effect=record):
            return fetch.main()

    def test_mixed_backlog_reaches_every_download_with_five_per_run(self):
        for _ in range(3):
            before = len(self.downloaded)
            self.assertEqual(self.run_main(), 0)
            self.assertEqual(len(self.downloaded) - before, 5)
        self.assertEqual(self.downloaded[:5], ['NEW0', 'OLD0', 'NEW1', 'OLD1', 'NEW2'])
        self.assertEqual(len(set(self.downloaded[:14])), 14)
        self.assertEqual(len(self.processed), 42)

    def test_unchanged_orders_do_not_use_slots_even_after_budget_exhausted(self):
        self.unchanged = {item['code'] for item in self.rechecks}
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.downloaded, ['NEW0', 'NEW1', 'NEW2', 'NEW3', 'NEW4'])
        self.assertEqual(len(self.processed), 14)
        queue = json.loads((self.root / fetch.QUEUE_FILE).read_text())['orders']
        self.assertEqual(queue[:2], ['NEW5', 'NEW6'])

    def test_all_unchanged_checks_finish_without_downloads(self):
        self.pending = []
        self.rechecks = [{'code': 'OLD' + str(i)} for i in range(20)]
        self.unchanged = {item['code'] for item in self.rechecks}
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(len(self.processed), 20)
        self.assertEqual(self.downloaded, [])

    def test_twenty_unchanged_before_changed_orders_do_not_exhaust_budget(self):
        self.pending = []
        self.rechecks = [{'code': 'OLD' + str(i)} for i in range(27)]
        self.unchanged = {'OLD' + str(i) for i in range(20)}
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(len(self.processed), 27)
        self.assertEqual(self.downloaded, ['OLD20', 'OLD21', 'OLD22', 'OLD23', 'OLD24'])
        queue = json.loads((self.root / fetch.QUEUE_FILE).read_text())['orders']
        self.assertEqual(queue[:2], ['OLD25', 'OLD26'])

    def test_failed_body_transfers_count_and_rotate(self):
        for _ in range(3):
            before = len(self.downloaded)
            self.assertEqual(self.run_main(process=lambda item: 'partial-error'), 1)
            self.assertEqual(len(self.downloaded) - before, 5)
        self.assertEqual(len(set(self.downloaded[:14])), 14)

    def test_cancellation_advances_only_the_attempted_order(self):
        def cancel(item):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_main(process=cancel)
        self.assertFalse((self.root / '_autofetch.lock').exists())
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.downloaded, ['NEW0', 'OLD0', 'NEW1', 'OLD1', 'NEW2', 'OLD2'])

    def test_dry_run_leaves_queue_unchanged(self):
        self.assertEqual(self.run_main(dry_run=True), 0)
        self.assertFalse((self.root / fetch.QUEUE_FILE).exists())
        self.assertEqual(self.downloaded, [])
        self.assertEqual(self.run_main(), 0)
        before = (self.root / fetch.QUEUE_FILE).read_bytes()
        self.assertEqual(self.run_main(dry_run=True), 0)
        self.assertEqual((self.root / fetch.QUEUE_FILE).read_bytes(), before)

    def test_expired_orders_drop_out_and_new_arrivals_join_tail(self):
        self.run_main()
        self.pending = [{'code': 'FRESH'}, self.pending[-1]]
        self.rechecks = [self.rechecks[-1]]
        self.downloaded.clear()
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.downloaded, ['NEW6', 'OLD6', 'FRESH'])

    def test_single_category_uses_all_slots_and_small_queue_is_not_repeated(self):
        for new_only in (True, False):
            with self.subTest(new_only=new_only):
                (self.root / fetch.QUEUE_FILE).unlink(missing_ok=True)
                orders = [{'code': str(i)} for i in range(7)]
                self.pending, self.rechecks = (orders, []) if new_only else ([], orders)
                self.downloaded.clear()
                self.assertEqual(self.run_main(), 0)
                self.assertEqual(self.downloaded, ['0', '1', '2', '3', '4'])
        self.pending, self.rechecks = [], [{'code': 'ONLY'}]
        self.downloaded.clear()
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.downloaded, ['ONLY'])

    def test_queue_survives_transition_from_new_order_to_recheck(self):
        self.run_main()
        completed = self.pending.pop(0)
        self.rechecks.append(completed)
        queue = fetch.work_queue(self.pending, self.rechecks, self.root)
        self.assertEqual(queue.count('NEW0'), 1)
        self.assertGreater(queue.index('NEW0'), queue.index('NEW6'))

    def test_bad_queue_or_failed_save_prevents_unrecorded_work(self):
        (self.root / fetch.QUEUE_FILE).write_text('invalid json')
        self.assertEqual(self.run_main(), 1)
        self.assertEqual(self.processed, [])
        (self.root / fetch.QUEUE_FILE).write_text(json.dumps({'orders': []}))
        with mock.patch.object(fetch, 'write_manifest_atomic', side_effect=OSError('disk full')):
            self.assertEqual(self.run_main(), 1)
        self.assertEqual(self.processed, [])
        self.assertFalse((self.root / '_autofetch.lock').exists())
