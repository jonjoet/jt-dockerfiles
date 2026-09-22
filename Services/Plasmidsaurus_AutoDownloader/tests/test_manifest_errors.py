import json
import os
import sys
from pathlib import Path
from unittest import mock

from support import PreservedTestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import plasmidsaurus_autofetch as fetch


class ManifestErrorTests(PreservedTestCase):
    def setUp(self):
        super().setUp()
        self.data = self.root / 'data'
        self.data.mkdir()
        self.bad = self.data / 'BAD'
        self.bad.mkdir()

    def snapshot(self):
        return {
            str(p.relative_to(self.bad)): (p.read_bytes() if p.is_file() else None,
                                          p.stat().st_mtime_ns)
            for p in [self.bad, *self.bad.rglob('*')]
        }

    def run_main(self, healthy=False, dry_run=False):
        items = [{'code': 'BAD', 'status': 'complete'}]
        if healthy:
            items.append({'code': 'HEALTHY', 'status': 'complete'})
        argv = ['autofetch', '--data-dir', str(self.data),
                '--scratch-dir', str(self.root / 'scratch')]
        if dry_run:
            argv.append('--dry-run')
        with mock.patch.dict(os.environ, {'PLASMIDSAURUS_CLIENT_ID': 'test',
                                          'PLASMIDSAURUS_CLIENT_SECRET': 'test'}), \
             mock.patch.object(sys, 'argv', argv), \
             mock.patch.object(fetch, 'setup_logging'), \
             mock.patch.object(fetch, 'get_access_token', return_value='token'), \
             mock.patch.object(fetch, 'get_items', return_value=items), \
             mock.patch.object(fetch, 'fetch_link', return_value=None) as links, \
             mock.patch.object(fetch, 'log') as logger:
            status = fetch.main()
        self.assertFalse((self.data / '_autofetch.lock').exists())
        return status, links, logger

    def test_bad_complete_fails_run_but_preserves_order_and_processes_healthy_order(self):
        (self.bad / '.complete').write_text('invalid json')
        # Even a valid older journal must not be used as a fallback.
        (self.bad / '.refresh.json').write_text(json.dumps({
            'files': {}, 'layout_version': 2, 'fetched_at': '2020-01-01T00:00:00Z',
        }))
        (self.bad / '.results.partial').mkdir()
        (self.bad / '.results.partial/staged').write_bytes(b'keep staged data')
        (self.bad / 'results').mkdir()
        (self.bad / 'results/local.fasta').write_bytes(b'keep published data')
        before = self.snapshot()
        status, links, logger = self.run_main(healthy=True)
        self.assertEqual(status, 1)
        self.assertEqual(links.call_args_list, [mock.call('token', 'HEALTHY', 'results'),
                                               mock.call('token', 'HEALTHY', 'reads')])
        self.assertTrue((self.data / 'HEALTHY/.complete').is_file())
        logger.error.assert_called_once()
        logger.info.assert_any_call('Run summary: %s', 'done-empty=1, manifest-error=1')
        self.assertEqual(self.snapshot(), before)

    def test_only_bad_manifest_fails_even_in_dry_run_and_ignore_suppresses_it(self):
        cases = [('.complete', 'bad json'), ('.complete', '[]'),
                 ('.complete', '{"files": []}'),
                 ('.complete', None), ('.refresh.json', 'bad json')]
        for index, (marker, contents) in enumerate(cases):
            with self.subTest(marker=marker, contents=contents):
                self.data = self.root / str(index)
                self.bad = self.data / 'BAD'
                self.bad.mkdir(parents=True)
                path = self.bad / marker
                if contents is None:
                    path.mkdir()  # Deterministic unreadable marker (OSError).
                else:
                    path.write_text(contents)
                before = self.snapshot()
                for dry_run in (False, True):
                    status, links, logger = self.run_main(dry_run=dry_run)
                    self.assertEqual(status, 1)
                    links.assert_not_called()
                    logger.error.assert_called_once()
                    logger.info.assert_any_call('Run summary: %s', 'manifest-error=1')
                    self.assertEqual(self.snapshot(), before)
                (self.bad / '.ignore').touch()
                ignored = self.snapshot()
                for dry_run in (False, True):
                    status, links, logger = self.run_main(dry_run=dry_run)
                    self.assertEqual(status, 0)
                    links.assert_not_called()
                    logger.error.assert_not_called()
                    logger.warning.assert_not_called()
                    self.assertEqual(self.snapshot(), ignored)
