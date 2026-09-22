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

    def run_main(self, dry_run=False, process=None):
        argv = ['autofetch', '--data-dir', str(self.root),
                '--scratch-dir', str(self.root / 'scratch')]
        if dry_run:
            argv.append('--dry-run')
        def record(item, *args):
            self.processed.append(item['code'])
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

    def test_mixed_backlog_reaches_every_order_with_five_per_run(self):
        for _ in range(3):
            before = len(self.processed)
            self.assertEqual(self.run_main(), 0)
            self.assertEqual(len(self.processed) - before, 5)
        self.assertEqual(self.processed[:5], ['NEW0', 'OLD0', 'NEW1', 'OLD1', 'NEW2'])
        self.assertEqual(len(set(self.processed[:14])), 14)

    def test_failures_rotate_instead_of_starving_other_orders(self):
        for _ in range(3):
            self.assertEqual(self.run_main(process=lambda item: 'partial-error'), 1)
        self.assertEqual(len(set(self.processed[:14])), 14)

    def test_cancellation_advances_only_the_attempted_order(self):
        def cancel(item):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_main(process=cancel)
        self.assertFalse((self.root / '_autofetch.lock').exists())
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.processed, ['NEW0', 'OLD0', 'NEW1', 'OLD1', 'NEW2', 'OLD2'])

    def test_dry_run_leaves_queue_unchanged(self):
        self.assertEqual(self.run_main(dry_run=True), 0)
        self.assertFalse((self.root / fetch.QUEUE_FILE).exists())
        self.assertEqual(self.run_main(), 0)
        before = (self.root / fetch.QUEUE_FILE).read_bytes()
        self.assertEqual(self.run_main(dry_run=True), 0)
        self.assertEqual((self.root / fetch.QUEUE_FILE).read_bytes(), before)

    def test_expired_orders_drop_out_and_new_arrivals_join_tail(self):
        self.run_main()
        self.pending = [{'code': 'FRESH'}, self.pending[-1]]
        self.rechecks = [self.rechecks[-1]]
        self.processed.clear()
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.processed, ['NEW6', 'OLD6', 'FRESH'])

    def test_single_category_uses_all_slots_and_small_queue_is_not_repeated(self):
        for new_only in (True, False):
            with self.subTest(new_only=new_only):
                (self.root / fetch.QUEUE_FILE).unlink(missing_ok=True)
                orders = [{'code': str(i)} for i in range(7)]
                self.pending, self.rechecks = (orders, []) if new_only else ([], orders)
                self.processed.clear()
                self.assertEqual(self.run_main(), 0)
                self.assertEqual(self.processed, ['0', '1', '2', '3', '4'])
        self.pending, self.rechecks = [], [{'code': 'ONLY'}]
        self.processed.clear()
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.processed, ['ONLY'])

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
