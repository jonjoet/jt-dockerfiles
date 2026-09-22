import gzip
import io
import json
import os
import sys
import urllib.error
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from support import PreservedTestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import plasmidsaurus_autofetch as fetch


class LateDeliveryTests(PreservedTestCase):
    def setUp(self):
        super().setUp()
        self.data = self.root / 'data'
        self.scratch = self.root / 'scratch'
        self.data.mkdir()
        self.scratch.mkdir()
        self.item = {'code': 'HYBRID', 'status': 'complete', 'product_name': 'hybrid',
                     'done_date': '2020-01-01T00:00:00Z'}
        self.folder = self.data / self.item['code']
        self.archives = {
            'results': {'ont.fasta': b'>ont\nACGT\n'},
            'reads': {'ont.fastq.gz': gzip.compress(b'@ont\nACGT\n+\n!!!!\n')},
        }
        self.etags = {'results': '"results-1"', 'reads': '"reads-1"'}
        self.requests = []
        self.conditional = True
        self.fail = None
        self.link_mock = mock.patch.object(fetch, 'fetch_link', side_effect=self.link)
        self.download_mock = mock.patch.object(fetch, 'download_to_scratch', side_effect=self.download)
        self.link_mock.start()
        self.download_mock.start()
        self.addCleanup(self.link_mock.stop)
        self.addCleanup(self.download_mock.stop)

    def link(self, token, code, kind):
        return 'https://example.test/' + kind if self.archives[kind] is not None else None

    def download(self, url, path, min_free_bytes, previous=None, before_download=None):
        kind = url.rsplit('/', 1)[1]
        self.requests.append((kind, previous))
        if self.fail == kind:
            raise fetch.RetryableError('simulated unavailable archive')
        if self.conditional and previous and previous.get('etag') == self.etags[kind]:
            return None
        if before_download:
            before_download()
        with zipfile.ZipFile(path, 'w') as zf:
            for name, body in self.archives[kind].items():
                zf.writestr(name, body)
        return {'archive_bytes': path.stat().st_size, 'etag': self.etags[kind]}

    def run_order(self, **kwargs):
        return fetch.process_item(self.item, 'token', self.data, self.scratch, 0, False, **kwargs)

    def manifest(self):
        return json.loads((self.folder / '.complete').read_text())

    def add_illumina(self):
        self.archives['results']['polished.fasta'] = b'>polished\nACGG\n'
        self.archives['reads']['illumina_R1.fastq.gz'] = gzip.compress(b'@illumina\nACGG\n+\n!!!!\n')
        self.etags = {'results': '"results-2"', 'reads': '"reads-2"'}

    def test_hybrid_late_reads_and_polished_fasta(self):
        self.assertEqual(self.run_order(), 'done')
        original = self.manifest()
        ont = self.folder / 'reads/ont.fastq.gz'
        os.utime(ont, (1000000000, 1000000000))
        self.add_illumina()
        self.assertEqual(self.run_order(), 'updated')
        self.assertEqual(ont.stat().st_mtime, 1000000000)
        self.assertEqual((self.folder / 'results/polished.fasta').read_bytes(), self.archives['results']['polished.fasta'])
        self.assertEqual((self.folder / 'reads/illumina_R1.fastq.gz').read_bytes(), self.archives['reads']['illumina_R1.fastq.gz'])
        current = self.manifest()
        self.assertEqual(current['fetched_at'], original['fetched_at'])
        self.assertEqual(current['files']['reads']['files'], 2)
        self.assertEqual(set(current['files']['results']['members']), {'ont.fasta', 'polished.fasta'})
        self.assertEqual(self.run_order(), 'unchanged')
        self.assertFalse((self.folder / '.refresh.json').exists())
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_same_name_same_size_revision_and_remote_omission(self):
        self.run_order()
        self.archives['results']['ont.fasta'] = b'>ont\nTGCA\n'
        self.archives['reads'] = {'illumina.fastq.gz': b'later'}
        self.etags = {'results': 'r2', 'reads': 'q2'}
        self.assertEqual(self.run_order(), 'updated')
        self.assertEqual((self.folder / 'results/ont.fasta').read_bytes(), b'>ont\nTGCA\n')
        self.assertTrue((self.folder / 'reads/ont.fastq.gz').exists())
        self.assertIn('ont.fastq.gz', self.manifest()['files']['reads']['members'])

    def test_fallback_without_conditional_support_does_not_rewrite_files(self):
        self.run_order()
        self.conditional = False
        path = self.folder / 'results/ont.fasta'
        os.utime(path, (1000000000, 1000000000))
        self.assertEqual(self.run_order(), 'unchanged')
        self.assertEqual(path.stat().st_mtime, 1000000000)

    def test_older_manifest_bootstraps_without_rewriting_existing_files(self):
        self.run_order()
        manifest = self.manifest()
        for kind in fetch.DATA_TYPES:
            manifest['files'][kind].pop('members')
            manifest['files'][kind].pop('remote')
        fetch.write_manifest_atomic(self.folder / '.complete', manifest)
        old = self.folder / 'reads/ont.fastq.gz'
        os.utime(old, (1000000000, 1000000000))
        self.add_illumina()
        self.assertEqual(self.run_order(), 'updated')
        self.assertEqual(old.stat().st_mtime, 1000000000)
        self.assertEqual(self.manifest()['fetched_at'], manifest['fetched_at'])

    def test_failure_keeps_previous_snapshot_and_retries_after_window(self):
        self.run_order()
        original = (self.folder / '.complete').read_bytes()
        self.add_illumina()
        self.fail = 'reads'
        self.assertEqual(self.run_order(), 'partial-error')
        self.assertEqual((self.folder / '.complete').read_bytes(), original)
        self.assertFalse((self.folder / 'results/polished.fasta').exists())
        self.assertTrue((self.folder / '.refresh.json').exists())
        self.fail = None
        self.assertEqual(self.run_order(recheck_days=0), 'updated')
        self.assertEqual(self.manifest()['fetched_at'], json.loads(original)['fetched_at'])

    def test_publication_interruption_retries_without_false_complete(self):
        self.run_order()
        self.add_illumina()
        replace = os.replace
        def fail_publish(source, target):
            if str(target).endswith('illumina_R1.fastq.gz'):
                raise OSError('simulated publication failure')
            return replace(source, target)
        with mock.patch.object(fetch.os, 'replace', side_effect=fail_publish):
            self.assertEqual(self.run_order(), 'partial-error')
        self.assertFalse((self.folder / '.complete').exists())
        self.assertTrue((self.folder / '.refresh.json').exists())
        self.assertEqual(self.run_order(recheck_days=0), 'updated')
        self.assertTrue((self.folder / 'reads/illumina_R1.fastq.gz').exists())

    def test_empty_order_and_initially_missing_reads_get_later_files(self):
        self.archives = {'results': None, 'reads': None}
        self.assertEqual(self.run_order(), 'done-empty')
        self.archives['results'] = {'ont.fasta': b'first'}
        self.assertEqual(self.run_order(), 'updated')
        self.archives['reads'] = {'illumina.fastq.gz': b'late'}
        self.assertEqual(self.run_order(), 'updated')

    def test_missing_previous_archive_is_retryable_not_deletion(self):
        self.run_order()
        previous = (self.folder / '.complete').read_bytes()
        self.archives['reads'] = None
        self.assertEqual(self.run_order(), 'partial-error')
        self.assertEqual((self.folder / '.complete').read_bytes(), previous)
        self.assertTrue((self.folder / 'reads/ont.fastq.gz').exists())

    def test_deleted_local_file_forces_download(self):
        self.run_order()
        (self.folder / 'reads/ont.fastq.gz').unlink()
        self.assertEqual(self.run_order(), 'updated')
        self.assertTrue((self.folder / 'reads/ont.fastq.gz').is_file())
        self.assertIsNone(self.requests[-1][1])

    def test_watch_window_and_selection_ignore_done_date_and_since(self):
        self.run_order()
        since = datetime.now(timezone.utc)
        new = {'code': 'NEW', 'status': 'complete'}
        pending, recent = fetch.select_work([self.item, new, new], since, self.data, 45)
        self.assertEqual(pending, [new])
        self.assertEqual(recent, [self.item])
        # The local watch list survives omission from /items or status changes.
        self.assertEqual(fetch.select_work([], since, self.data, 45)[1][0]['code'], 'HYBRID')
        processing = dict(self.item, status='processing')
        self.assertEqual(fetch.select_work([processing], since, self.data, 45)[1], [processing])
        self.assertEqual(fetch.select_work([self.item], since, self.data, 0), ([], []))
        old = self.manifest()
        old['fetched_at'] = (since - timedelta(days=46)).isoformat()
        fetch.write_manifest_atomic(self.folder / '.complete', old)
        self.assertEqual(fetch.select_work([self.item], None, self.data, 45), ([], []))
        self.assertEqual(fetch.select_work([self.item], None, self.data, 60)[1], [self.item])
        self.assertEqual(self.run_order(), 'skip-done')
        fetch.write_manifest_atomic(self.folder / '.refresh.json', old)
        self.assertEqual(fetch.select_work([], None, self.data, 0)[1][0]['code'], 'HYBRID')

    def test_window_boundary_and_bad_dates(self):
        now = datetime.now(timezone.utc)
        exact = {'fetched_at': (now - timedelta(days=45)).isoformat()}
        self.assertTrue(fetch.within_recheck_window(exact, 45, now))
        self.assertFalse(fetch.within_recheck_window(exact, 45, now + timedelta(seconds=1)))
        for value in (None, '', 'not-a-date', 12):
            self.assertFalse(fetch.within_recheck_window({'fetched_at': value}, 45, now))

    def test_dry_run_does_not_fetch_or_modify_order(self):
        self.run_order()
        original = (self.folder / '.complete').read_bytes()
        self.requests.clear()
        self.assertEqual(fetch.process_item(self.item, 'token', self.data, self.scratch, 0, True), 'would-recheck')
        self.assertEqual(self.requests, [])
        self.assertEqual((self.folder / '.complete').read_bytes(), original)
        self.assertFalse((self.folder / '.refresh.json').exists())

    def test_unsafe_refresh_leaves_existing_data_untouched(self):
        self.run_order()
        original = (self.folder / '.complete').read_bytes()
        self.archives['results'] = {'../outside': b'unsafe'}
        self.etags['results'] = 'unsafe'
        self.assertEqual(self.run_order(), 'partial-error')
        self.assertEqual((self.folder / '.complete').read_bytes(), original)
        self.assertFalse((self.folder / 'outside').exists())

    def test_refresh_rejects_case_collision_and_symlink(self):
        self.run_order()
        self.archives['results']['ONT.fasta'] = b'collision'
        self.etags['results'] = 'new'
        self.assertEqual(self.run_order(), 'partial-error')
        del self.archives['results']['ONT.fasta']
        target = self.folder / 'results/ont.fasta'
        target.unlink()
        outside = self.root / 'outside'
        outside.write_bytes(b'keep')
        target.symlink_to(outside)
        self.assertEqual(self.run_order(), 'partial-error')
        self.assertEqual(outside.read_bytes(), b'keep')

    def test_main_downloads_five_new_orders_despite_unchanged_recheck(self):
        self.run_order()
        items = [{'code': 'NEW' + str(i), 'status': 'complete'} for i in range(7)]
        with mock.patch.dict(os.environ, {'PLASMIDSAURUS_CLIENT_ID': 'test', 'PLASMIDSAURUS_CLIENT_SECRET': 'test'}), \
             mock.patch.object(sys, 'argv', ['autofetch', '--data-dir', str(self.data), '--scratch-dir', str(self.scratch), '--recheck-days', '45']), \
             mock.patch.object(fetch, 'setup_logging'), \
             mock.patch.object(fetch, 'get_access_token', return_value='token'), \
             mock.patch.object(fetch, 'get_items', return_value=items):
            self.assertEqual(fetch.main(), 0)
            first = [i['code'] for i in items if (self.data / i['code'] / '.complete').exists()]
            self.assertEqual(fetch.main(), 0)
            second = [i['code'] for i in items if (self.data / i['code'] / '.complete').exists()]
        self.assertEqual(first, ['NEW0', 'NEW1', 'NEW2', 'NEW3', 'NEW4'])
        self.assertEqual(second, [i['code'] for i in items])
        self.assertFalse((self.data / '_autofetch.lock').exists())

    def test_exhausted_budget_preserves_validators_and_checks_unchanged(self):
        self.run_order()
        budget = fetch.DownloadBudget(0)
        self.assertEqual(self.run_order(budget=budget), 'unchanged')
        original = (self.folder / '.complete').read_bytes()
        self.add_illumina()
        self.assertEqual(self.run_order(budget=budget), 'deferred')
        self.assertEqual((self.folder / '.complete').read_bytes(), original)
        self.assertFalse((self.folder / '.refresh.json').exists())
        self.assertFalse((self.folder / 'results/polished.fasta').exists())
        self.assertEqual(self.run_order(budget=fetch.DownloadBudget(1)), 'updated')

    def test_two_archives_share_one_download_slot(self):
        budget = fetch.DownloadBudget(1)
        self.assertEqual(self.run_order(budget=budget), 'done')
        self.assertEqual(budget.orders, {'HYBRID'})
        self.assertEqual(self.manifest()['files']['reads']['files'], 1)

    def test_reads_only_update_deferred_after_unchanged_results(self):
        self.run_order()
        self.archives['reads']['illumina.fastq.gz'] = b'later'
        self.etags['reads'] = 'reads-2'
        original = (self.folder / '.complete').read_bytes()
        self.assertEqual(self.run_order(budget=fetch.DownloadBudget(0)), 'deferred')
        self.assertEqual((self.folder / '.complete').read_bytes(), original)
        self.assertFalse((self.folder / '.refresh.json').exists())
        self.assertEqual(self.run_order(budget=fetch.DownloadBudget(1)), 'updated')
        self.assertEqual((self.folder / 'reads/illumina.fastq.gz').read_bytes(), b'later')

    def test_legacy_inventory_is_not_read_for_deferred_order(self):
        self.run_order()
        manifest = self.manifest()
        for value in manifest['files'].values():
            value.pop('members')
        fetch.write_manifest_atomic(self.folder / '.complete', manifest)
        with mock.patch.object(fetch, 'inventory_directory') as inventory:
            self.assertEqual(self.run_order(budget=fetch.DownloadBudget(0)), 'deferred')
            inventory.assert_not_called()
        self.assertFalse((self.folder / '.refresh.json').exists())

    def test_fallback_download_counts_even_when_members_match(self):
        self.run_order()
        self.conditional = False
        budget = fetch.DownloadBudget(1)
        self.assertEqual(self.run_order(budget=budget), 'unchanged')
        self.assertEqual(budget.orders, {'HYBRID'})

    def test_bad_recheck_configuration_fails_before_api(self):
        for value in ('-1', '1.5', 'invalid', '1000000000'):
            with self.subTest(value=value), \
                 mock.patch.object(sys, 'argv', ['autofetch', '--data-dir', str(self.data), '--recheck-days', value]), \
                 mock.patch.object(fetch, 'setup_logging'), \
                 mock.patch.object(fetch, 'get_access_token') as token:
                self.assertEqual(fetch.main(), 2)
                token.assert_not_called()

    def test_legacy_and_malformed_markers_are_not_overwritten(self):
        self.folder.mkdir()
        marker = self.folder / '.complete'
        for contents in ('not json', json.dumps({'files': {}, 'fetched_at': datetime.now(timezone.utc).isoformat()})):
            marker.write_text(contents)
            self.assertEqual(fetch.select_work([self.item], None, self.data, 45), ([], []))
            self.assertEqual(marker.read_text(), contents)


class DownloadTests(PreservedTestCase):
    def test_budget_exhaustion_closes_response_without_reading_body(self):
        response = io.BytesIO(b'archive')
        response.headers = {'Content-Length': '7'}
        budget = fetch.DownloadBudget(0)
        path = self.root / 'archive.zip'
        with mock.patch.object(fetch.urllib.request, 'urlopen', return_value=response), \
             mock.patch.object(response, 'read', wraps=response.read) as read:
            with self.assertRaises(fetch.DownloadDeferred):
                fetch.download_to_scratch('https://example.test/data', path, 0,
                                          before_download=lambda: budget.claim('ORDER'))
            read.assert_not_called()
        self.assertTrue(response.closed)
        self.assertFalse(path.exists())
        self.assertFalse((self.root / 'archive.zip.part').exists())

    def test_conditional_get_304_does_not_write_or_read_body(self):
        path = self.root / 'archive.zip'
        error = urllib.error.HTTPError('https://example.test/new-signature', 304, 'Not Modified', {}, None)
        before_download = mock.Mock()
        with mock.patch.object(fetch.urllib.request, 'urlopen', side_effect=error) as urlopen:
            result = fetch.download_to_scratch('https://example.test/new-signature', path, 0,
                                               {'etag': '"version1"', 'last_modified': 'old'},
                                               before_download=before_download)
        self.assertIsNone(result)
        before_download.assert_not_called()
        self.assertEqual(urlopen.call_args[0][0].get_header('If-none-match'), '"version1"')
        self.assertIsNone(urlopen.call_args[0][0].get_header('If-modified-since'))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_last_modified_and_missing_validators(self):
        for previous in ({'last_modified': 'Tue, 22 Sep 2026 01:00:00 GMT'}, {}):
            response = io.BytesIO(b'archive')
            response.headers = {'Content-Length': '7', 'ETag': '"new"', 'Last-Modified': 'today'}
            with mock.patch.object(fetch.urllib.request, 'urlopen', return_value=response) as urlopen:
                metadata = fetch.download_to_scratch('https://example.test/data?secret=not-stored', self.root / 'zip', 0, previous)
            self.assertEqual(urlopen.call_args[0][0].get_header('If-modified-since'), previous.get('last_modified'))
            self.assertEqual(metadata, {'archive_bytes': 7, 'etag': '"new"', 'last_modified': 'today'})
            self.assertNotIn('secret', json.dumps(metadata))
            self.assertEqual((self.root / 'zip').read_bytes(), b'archive')

    def test_short_download_never_publishes(self):
        response = io.BytesIO(b'short')
        response.headers = {'Content-Length': '100'}
        path = self.root / 'zip'
        budget = fetch.DownloadBudget(1)
        with mock.patch.object(fetch.urllib.request, 'urlopen', return_value=response):
            with self.assertRaises(fetch.RetryableError):
                fetch.download_to_scratch('https://example.test/data', path, 0,
                                          before_download=lambda: budget.claim('ORDER'))
        self.assertEqual(budget.orders, {'ORDER'})
        self.assertFalse(path.exists())
        self.assertFalse((self.root / 'zip.part').exists())

    def test_api_auth_rate_limit_and_server_errors_are_not_missing_data(self):
        for status in (400, 401, 403, 429, 500):
            with self.subTest(status=status), mock.patch.object(fetch, '_api_get', side_effect=urllib.error.HTTPError('https://example.test', status, 'error', {}, None)):
                with self.assertRaises(fetch.RetryableError):
                    fetch.fetch_link('token', 'HYBRID', 'reads')
        for status in (404, 410):
            with mock.patch.object(fetch, '_api_get', side_effect=urllib.error.HTTPError('https://example.test', status, 'missing', {}, None)):
                self.assertIsNone(fetch.fetch_link('token', 'HYBRID', 'reads'))
