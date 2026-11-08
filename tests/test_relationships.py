import argparse
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import relationships as r


class FakeAPI:
    def __init__(self, source='101', username='reader', outcome=None, failure=None):
        self.source = source
        self.username = username
        self.outcome = outcome if outcome is not None else {'data': {'following': True}}
        self.failure = failure
        self.calls = []

    def __call__(self, method, path, token, body=None):
        self.calls.append((method, path, body))
        if path == '/users/me':
            return {'data': {'id': self.source, 'username': self.username}}
        if path.startswith('/users/by/username/'):
            return {'data': {'id': '202', 'username': 'builder'}}
        if self.failure:
            raise self.failure
        return self.outcome


class RelationshipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.args = argparse.Namespace(target='builder', action='follow', expected_user_id='101',
            expected_username='reader', confirm='follow @builder from @reader', log=self.root / 'private/log.jsonl')
        self.env = patch.dict(os.environ, {'X_USER_ACCESS_TOKEN': 'TEST_PLACEHOLDER_NOT_A_CREDENTIAL'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_action(self, api):
        with redirect_stdout(io.StringIO()):
            r.execute(self.args, api=api)

    def test_bulk_default_is_offline_and_deduplicates(self):
        source = self.root / 'people.csv'
        source.write_text('handle\nbuilder\n@Builder\n')
        output = io.StringIO()
        with patch.object(r, 'request', side_effect=AssertionError('network prohibited')), redirect_stdout(output):
            self.assertEqual(r.main(['--csv', str(source)]), 0)
        self.assertIn('1 unique planned actions; 0 network calls', output.getvalue())
        self.assertFalse(self.args.log.exists())

    def test_bulk_cannot_execute(self):
        output = io.StringIO()
        with redirect_stderr(output):
            self.assertEqual(r.main(['--execute']), 2)
        self.assertIn('Bulk execution is disabled', output.getvalue())

    def test_missing_confirmation_performs_zero_calls(self):
        api = FakeAPI()
        self.args.confirm = 'yes'
        with self.assertRaises(r.Refusal):
            self.run_action(api)
        self.assertEqual(api.calls, [])

    def test_wrong_account_stops_before_target_or_write(self):
        api = FakeAPI(source='303')
        with self.assertRaises(r.Refusal):
            self.run_action(api)
        self.assertEqual([x[0] for x in api.calls], ['GET'])

    def test_wrong_username_also_stops(self):
        api = FakeAPI(username='other')
        with self.assertRaises(r.Refusal):
            self.run_action(api)
        self.assertEqual(len(api.calls), 1)

    def test_success_exact_endpoint_and_secret_free_receipt(self):
        api = FakeAPI()
        self.run_action(api)
        self.assertEqual(api.calls[-1], ('POST', '/users/101/following', {'target_user_id': '202'}))
        raw = self.args.log.read_text()
        self.assertNotIn(os.environ['X_USER_ACCESS_TOKEN'], raw)
        self.assertEqual(json.loads(raw.splitlines()[-1])['status'], 'confirmed')
        self.assertEqual(self.args.log.stat().st_mode & 0o777, 0o600)

    def test_recorded_success_not_replayed(self):
        self.run_action(FakeAPI())
        api = FakeAPI()
        with self.assertRaisesRegex(r.Refusal, 'already recorded'):
            self.run_action(api)
        self.assertTrue(all(x[0] == 'GET' for x in api.calls))

    def test_pending_is_reported_separately(self):
        self.run_action(FakeAPI(outcome={'data': {'following': False, 'pending_follow': True}}))
        self.assertEqual(json.loads(self.args.log.read_text().splitlines()[-1])['status'], 'pending')

    def test_unfollow_checks_false_not_http_status(self):
        self.args.action = 'unfollow'
        self.args.confirm = 'unfollow @builder from @reader'
        api = FakeAPI(outcome={'data': {'following': False}})
        self.run_action(api)
        self.assertEqual(api.calls[-1], ('DELETE', '/users/101/following/202', None))

    def test_200_with_errors_is_unknown_and_not_retried(self):
        api = FakeAPI(outcome={'data': {'following': True}, 'errors': [{'title': 'partial'}]})
        with self.assertRaises(r.Refusal):
            self.run_action(api)
        self.assertEqual(sum(x[0] == 'POST' for x in api.calls), 1)
        self.assertEqual(json.loads(self.args.log.read_text().splitlines()[-1])['status'], 'unknown')
        retry = FakeAPI()
        with self.assertRaisesRegex(r.Refusal, 'unresolved'):
            self.run_action(retry)
        self.assertEqual(sum(x[0] == 'POST' for x in retry.calls), 0)

    def test_429_stops_without_retry(self):
        api = FakeAPI(failure=r.Refusal('HTTP 429; stopped'))
        with self.assertRaisesRegex(r.Refusal, '429'):
            self.run_action(api)
        self.assertEqual(sum(x[0] == 'POST' for x in api.calls), 1)

    def test_timeout_records_unknown_outcome(self):
        api = FakeAPI(failure=r.Refusal('API transport failure'))
        with self.assertRaises(r.Refusal):
            self.run_action(api)
        self.assertEqual(json.loads(self.args.log.read_text().splitlines()[-1])['status'], 'unknown')

    def test_recent_other_write_blocks_new_write(self):
        self.args.log.parent.mkdir(parents=True)
        r.append_receipt(self.args.log, {'source_id': '101', 'target_id': '999',
                         'status': 'intent', 'epoch': r.time.time()})
        api = FakeAPI()
        with self.assertRaisesRegex(r.Refusal, 'minimum interval'):
            self.run_action(api)
        self.assertTrue(all(x[0] == 'GET' for x in api.calls))

    def test_target_mismatch_and_self_target_refused(self):
        for data in [{'id': '202', 'username': 'someone_else'}, {'id': '101', 'username': 'builder'}]:
            api = FakeAPI()
            def answer(method, path, token, body=None):
                if path.startswith('/users/by/username/'):
                    api.calls.append((method, path, body))
                    return {'data': data}
                return api(method, path, token, body)
            with self.assertRaises(r.Refusal):
                self.run_action(answer)
            self.assertTrue(all(x[0] == 'GET' for x in api.calls))

    def test_no_oauth_default_network_or_home_write(self):
        script = Path(r.__file__).with_name('oauth_session.py')
        env = dict(os.environ, HOME=str(self.root), X_CLIENT_ID='')
        result = subprocess.run([sys.executable, str(script), '--dry-run'], env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn('0 network calls', result.stdout)
        self.assertNotIn('TEST_PLACEHOLDER', result.stdout + result.stderr)

    def test_existing_receipt_permissions_are_tightened(self):
        self.args.log.parent.mkdir(parents=True)
        self.args.log.write_text('')
        self.args.log.chmod(0o644)
        self.run_action(FakeAPI())
        self.assertEqual(self.args.log.stat().st_mode & 0o777, 0o600)

    def test_receipt_symlink_is_refused_before_api(self):
        self.args.log.parent.mkdir(parents=True)
        other = self.root / 'other'
        other.write_text('untouched')
        self.args.log.symlink_to(other)
        api = FakeAPI()
        with self.assertRaises(OSError):
            self.run_action(api)
        self.assertEqual(api.calls, [])
        self.assertEqual(other.read_text(), 'untouched')

    def test_malformed_data_records_unknown(self):
        with self.assertRaises(r.Refusal):
            self.run_action(FakeAPI(outcome={'data': ['unexpected']}))
        self.assertEqual(json.loads(self.args.log.read_text().splitlines()[-1])['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
