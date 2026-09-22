import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
from unittest import mock

from support import PreservedTestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import plasmidsaurus_autofetch as fetch


class RateLimitingTests(PreservedTestCase):
    def setUp(self):
        super().setUp()
        self.epoch = int(time.time())
        self.elapsed = 0.0
        self.sleeps = []
        for patch in (mock.patch.object(fetch.time, 'sleep', side_effect=self.sleep),
                      mock.patch.object(fetch.time, 'monotonic', side_effect=lambda: self.elapsed),
                      mock.patch.object(fetch.time, 'time', side_effect=lambda: self.epoch + self.elapsed),
                      mock.patch.object(fetch, '_http', fetch.HttpClient())):
            patch.start()
            self.addCleanup(patch.stop)
        self.req = urllib.request.Request('https://example.test/data?secret=do-not-log')

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.elapsed += seconds

    def error(self, code=429, retry_after=None):
        headers = {} if retry_after is None else {'Retry-After': retry_after}
        body = io.BytesIO(b'error body with secret')
        return urllib.error.HTTPError(self.req.full_url, code, 'error', headers, body)

    def response(self, data=b'{}'):
        response = io.BytesIO(data)
        response.headers = {'Content-Length': str(len(data))}
        return response

    def test_api_spacing_includes_auth_lists_and_links_but_not_archive_requests(self):
        starts = []
        responses = [b'{"access_token":"token"}', b'[]', b'[]', b'{"link":"https://example.test/archive"}', b'zip']
        def open_response(*args, **kwargs):
            starts.append(self.elapsed)
            return self.response(responses.pop(0))
        with mock.patch.object(fetch.urllib.request, 'urlopen', side_effect=open_response):
            self.assertEqual(fetch.get_access_token('id', 'secret'), 'token')
            self.assertEqual(fetch.get_items('token'), [])
            link = fetch.fetch_link('token', 'ORDER', 'results')
            fetch.download_to_scratch(link, self.root / 'archive.zip', 0)
        self.assertEqual(starts, [0, 2, 4, 6, 6])
        self.assertEqual(self.sleeps, [2, 2, 2])

    def test_retry_after_seconds_and_http_date_close_errors_and_retry_same_request(self):
        for index, header in enumerate(('7', formatdate(self.epoch + 20, usegmt=True))):
            with self.subTest(header=header):
                error = self.error(retry_after=header)
                before = self.elapsed
                with mock.patch.object(fetch.urllib.request, 'urlopen', side_effect=[error, self.response()]) as opener:
                    with fetch._http.open(self.req):
                        pass
                self.assertTrue(error.fp.closed)
                self.assertEqual(self.elapsed, 7 if index == 0 else 20)
                self.assertGreater(self.elapsed, before)
                self.assertEqual([call.args[0] for call in opener.call_args_list], [self.req, self.req])

    def test_missing_or_malformed_retry_after_uses_exponential_fallback(self):
        errors = [self.error(), self.error(retry_after='nonsense'), self.error(retry_after='-5')]
        with mock.patch.object(fetch.urllib.request, 'urlopen', side_effect=errors + [self.response()]):
            with fetch._http.open(self.req):
                pass
        self.assertEqual(self.sleeps, [30, 60, 120])
        self.assertTrue(all(error.fp.closed for error in errors))

    def test_zero_and_past_retry_after_have_minimum_delay(self):
        for header in ('0', formatdate(self.epoch - 10, usegmt=True)):
            with mock.patch.object(fetch.urllib.request, 'urlopen', side_effect=[self.error(retry_after=header), self.response()]):
                with fetch._http.open(self.req):
                    pass
        self.assertEqual(self.sleeps, [1, 1])

    def test_retry_exhaustion_is_bounded_and_logs_no_signed_url(self):
        errors = [self.error() for _ in range(4)]
        with mock.patch.object(fetch.urllib.request, 'urlopen', side_effect=errors) as opener, \
             self.assertLogs(fetch.log, level='WARNING') as logs:
            with self.assertRaises(fetch.RateLimited) as caught:
                fetch._http.open(self.req)
        self.assertEqual(opener.call_count, 4)
        self.assertEqual(self.sleeps, [30, 60, 120])
        self.assertEqual(caught.exception.retry_at, self.epoch + 210 + 240)
        self.assertNotIn('secret', str(caught.exception) + '\n'.join(logs.output))
        self.assertTrue(all(error.fp.closed for error in errors))

    def test_long_retry_after_stops_without_shortening_server_delay(self):
        with mock.patch.object(fetch.urllib.request, 'urlopen', side_effect=self.error(retry_after='600')) as opener:
            with self.assertRaises(fetch.RateLimited) as caught:
                fetch._http.open(self.req)
        self.assertEqual(opener.call_count, 1)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(caught.exception.retry_at, self.epoch + 600)

    def test_wait_budget_is_shared_across_requests(self):
        with mock.patch.object(fetch.urllib.request, 'urlopen', side_effect=[
            self.error(retry_after='200'), self.response(), self.error(retry_after='101'),
        ]) as opener:
            with fetch._http.open(self.req):
                pass
            with self.assertRaises(fetch.RateLimited):
                fetch._http.open(self.req)
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(self.sleeps, [200])

    def test_other_http_errors_are_not_retried(self):
        for status in (304, 400, 401, 403, 404, 410, 500):
            with self.subTest(status=status), \
                 mock.patch.object(fetch.urllib.request, 'urlopen', side_effect=self.error(code=status)) as opener:
                with self.assertRaises(urllib.error.HTTPError):
                    fetch._http.open(self.req)
                self.assertEqual(opener.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_archive_retry_keeps_validators_and_only_body_download_uses_slot(self):
        for status in (304, 200):
            with self.subTest(status=status):
                budget = fetch.DownloadBudget(1)
                path = self.root / str(status)
                response = self.error(code=304) if status == 304 else self.response(b'archive')
                with mock.patch.object(fetch.urllib.request, 'urlopen', side_effect=[self.error(retry_after='1'), response]) as opener:
                    result = fetch.download_to_scratch(self.req.full_url, path, 0,
                                                       previous={'etag': 'v1'},
                                                       before_download=lambda: budget.claim('ORDER'))
                self.assertEqual(budget.orders, set() if status == 304 else {'ORDER'})
                self.assertEqual(result is None, status == 304)
                self.assertTrue(all(call.args[0].get_header('If-none-match') == 'v1'
                                    for call in opener.call_args_list))
                self.assertFalse(path.with_suffix('.part').exists())

    def run_main(self, items, links, extra_args=()):
        with mock.patch.dict(os.environ, {'PLASMIDSAURUS_CLIENT_ID': 'id',
                                          'PLASMIDSAURUS_CLIENT_SECRET': 'secret'}), \
             mock.patch.object(sys, 'argv', ['autofetch', '--data-dir', str(self.root),
                                             '--scratch-dir', str(self.root / 'scratch'), *extra_args]), \
             mock.patch.object(fetch, 'setup_logging'), \
             mock.patch.object(fetch, 'get_access_token', return_value='token') as token, \
             mock.patch.object(fetch, 'get_items', return_value=items), \
             mock.patch.object(fetch, 'fetch_link', side_effect=links) as fetch_link:
            status = fetch.main()
        self.assertFalse((self.root / '_autofetch.lock').exists())
        return status, token, fetch_link

    def test_throttle_stops_batch_restores_queue_and_preserves_published_snapshot(self):
        items = [{'code': code, 'status': 'complete'} for code in ('A', 'B', 'C')]
        queue_path = self.root / fetch.QUEUE_FILE
        queue_path.write_text(json.dumps({'orders': ['A', 'B', 'C']}))
        folder = self.root / 'B'
        folder.mkdir()
        manifest = json.dumps({'layout_version': 2, 'files': {},
                               'fetched_at': datetime.now(timezone.utc).isoformat()})
        (folder / '.complete').write_text(manifest)
        def links(token, code, kind):
            if code == 'B':
                return fetch._read_json(self.req)
            return None
        with mock.patch.object(fetch.urllib.request, 'urlopen', side_effect=[self.error() for _ in range(4)]) as opener:
            status, _, called = self.run_main(items, links)
        self.assertEqual(status, 1)
        self.assertEqual(opener.call_count, 4)
        self.assertEqual([call.args[1] for call in called.call_args_list], ['A', 'A', 'B'])
        self.assertEqual(json.loads(queue_path.read_text())['orders'], ['B', 'C', 'A'])
        self.assertEqual((folder / '.complete').read_text(), manifest)
        self.assertFalse((folder / '.refresh.json').exists())
        self.assertTrue((self.root / 'A/.complete').exists())
        self.assertFalse((self.root / 'C').exists())
        before = queue_path.read_bytes()
        status, token, called = self.run_main(items, lambda *args: None)
        self.assertEqual(status, 1)
        token.assert_not_called()
        called.assert_not_called()
        self.assertEqual(queue_path.read_bytes(), before)
        self.sleep(241)
        status, token, called = self.run_main(items, lambda *args: None)
        self.assertEqual(status, 0)
        token.assert_called_once()
        self.assertEqual([call.args[1] for call in called.call_args_list][:4], ['B', 'B', 'C', 'C'])

    def test_startup_throttle_records_cooldown_without_touching_queue(self):
        queue = self.root / fetch.QUEUE_FILE
        queue.write_text(json.dumps({'orders': ['A']}))
        before = queue.read_bytes()
        with mock.patch.object(sys, 'argv', ['autofetch', '--data-dir', str(self.root),
                                             '--scratch-dir', str(self.root / 'scratch')]), \
             mock.patch.dict(os.environ, {'PLASMIDSAURUS_CLIENT_ID': 'id', 'PLASMIDSAURUS_CLIENT_SECRET': 'secret'}), \
             mock.patch.object(fetch, 'setup_logging'), \
             mock.patch.object(fetch.urllib.request, 'urlopen', side_effect=self.error(retry_after='600')) as opener:
            self.assertEqual(fetch.main(), 1)
        self.assertEqual(opener.call_count, 1)
        self.assertEqual(queue.read_bytes(), before)
        self.assertEqual(json.loads((self.root / fetch.COOLDOWN_FILE).read_text())['retry_at'], self.epoch + 600)

    def test_throttle_retains_earlier_deferred_orders_ahead_of_current_order(self):
        items = [{'code': code, 'status': 'complete'} for code in ('A', 'B', 'C', 'D')]
        with mock.patch.object(fetch, 'process_item', side_effect=[
            'deferred', 'done', fetch.RateLimited(self.epoch + 60),
        ]) as process:
            status, _, _ = self.run_main(items, lambda *args: None)
        self.assertEqual(status, 1)
        self.assertEqual(process.call_count, 3)
        self.assertEqual(json.loads((self.root / fetch.QUEUE_FILE).read_text())['orders'], ['A', 'C', 'D', 'B'])

    def test_dry_run_honors_cooldown_without_advancing_queue(self):
        queue = self.root / fetch.QUEUE_FILE
        queue.write_text(json.dumps({'orders': ['A']}))
        (self.root / fetch.COOLDOWN_FILE).write_text(json.dumps({'retry_at': self.epoch + 60}))
        before = queue.read_bytes()
        status, token, links = self.run_main([], lambda *args: None, ['--dry-run'])
        self.assertEqual(status, 1)
        token.assert_not_called()
        links.assert_not_called()
        self.assertEqual(queue.read_bytes(), before)

    def test_invalid_cooldown_fails_before_network(self):
        for value in ('bad', '[]', '{"retry_at": "nan"}'):
            with self.subTest(value=value):
                (self.root / fetch.COOLDOWN_FILE).write_text(value)
                status, token, _ = self.run_main([], lambda *args: None)
                self.assertEqual(status, 1)
                token.assert_not_called()

    def test_interval_configuration_validation_and_cli_override(self):
        for value in ('-1', '61', 'nan', 'inf', 'invalid', ''):
            with self.subTest(value=value), mock.patch.dict(os.environ, {'PLASMIDSAURUS_API_INTERVAL': value}):
                status, token, _ = self.run_main([], lambda *args: None)
                self.assertEqual(status, 2)
                token.assert_not_called()
        for value in ('0', '0.5', '60'):
            with self.subTest(value=value), mock.patch.dict(os.environ, {'PLASMIDSAURUS_API_INTERVAL': 'invalid'}):
                status, _, _ = self.run_main([], lambda *args: None, ['--api-interval', value])
                self.assertEqual(status, 0)
                self.assertEqual(fetch._http.api_interval, float(value))
