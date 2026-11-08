"""Offline safety acceptance tests; no credentials, paid calls or live X writes."""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import apify_fetch as af
import batch as b
import graph as g
import kit_common as k
import oauth_session as oauth
from relationships import Refusal

OWNER = {'id': '101', 'handle': 'reader'}


class FakeX:
    def __init__(self, outcome=None, source='101', username='reader', target='202'):
        self.calls = []
        self.source, self.username, self.target = source, username, target
        self.outcome = outcome or {'data': {'following': True}}

    def __call__(self, method, url, bearer=None, body=None):
        self.calls.append((method, url, body))
        if url.endswith('/users/me'):
            return {'data': {'id': self.source, 'username': self.username}}
        if '/users/by/username/' in url:
            return {'data': {'id': self.target, 'username': url.rsplit('/', 1)[-1]}}
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return deepcopy(self.outcome)

    @property
    def writes(self):
        return [call for call in self.calls if call[0] != 'GET']


class V2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        self.graph = g.envelope([], OWNER, 'following', 'fixture', False)
        self.plan = {'version': 1, 'account': OWNER, 'created_at': k.stamp(),
                     'graph_sha256': k.digest(self.graph), 'actions': [{
                         'target_id': '202', 'handle': 'builder', 'action': 'follow',
                         'before_following': False, 'reason': 'Relevant authored examples reviewed by the agent.'}]}
        with redirect_stdout(io.StringIO()):
            b.init_state(self.state, OWNER)
        self.env = patch.dict(os.environ, {'X_USER_ACCESS_TOKEN': 'FAKE_X_TOKEN', 'APIFY_TOKEN': 'FAKE_APIFY_TOKEN'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def fetch(self, *args, **kwargs):
        result = deepcopy(self.graph)
        result['complete'] = True
        result['provider'] = 'x'
        return result

    def apply(self, api=None, **kwargs):
        api = api or FakeX()
        with redirect_stdout(io.StringIO()):
            b.apply_plan(self.plan, self.graph, self.state, k.digest(self.plan),
                         f"apply {len(self.plan['actions'])} changes from @reader", api=api,
                         fetch=kwargs.pop('fetch', self.fetch), **kwargs)
        return api

    def test_preview_zero_network_no_state_write(self):
        before = (self.state / 'state.json').read_text()
        with patch.object(k, 'http', side_effect=AssertionError('network')), redirect_stdout(io.StringIO()) as output:
            result = b.preview(self.plan, self.graph)
        self.assertEqual(result, k.digest(self.plan))
        self.assertIn('"network_calls": 0', output.getvalue())
        self.assertIn('"account": {"id": "101", "handle": "reader"}', output.getvalue())
        self.assertIn('"graph_fetched_at":', output.getvalue())
        self.assertIn('"graph_snapshot_age_seconds":', output.getvalue())
        self.assertEqual(before, (self.state / 'state.json').read_text())

    def test_plan_tampering_requires_new_digest(self):
        original = k.digest(self.plan)
        self.plan['actions'][0]['reason'] = 'Changed rationale.'
        api = FakeX()
        with self.assertRaisesRegex(Refusal, 'digest'):
            b.apply_plan(self.plan, self.graph, self.state, original, 'apply 1 changes from @reader', api=api)
        self.assertEqual(api.calls, [])

    def test_graph_tampering_refused(self):
        self.graph['complete'] = True
        with self.assertRaisesRegex(Refusal, 'graph_sha256'):
            self.apply()

    def test_account_mismatch_zero_writes(self):
        api = FakeX(source='999')
        with self.assertRaises(Refusal):
            self.apply(api)
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.writes, [])

    def test_malformed_account_or_target_response_refused(self):
        for malformed_path in ('/users/me', '/users/by/username/builder'):
            api = FakeX()
            def malformed(method, url, bearer=None, body=None):
                if url.endswith(malformed_path):
                    return []
                return api(method, url, bearer, body)
            with self.subTest(path=malformed_path), self.assertRaises(Refusal):
                self.apply(malformed)
            self.assertEqual(api.writes, [])

    def test_target_mismatch_zero_writes(self):
        api = FakeX(target='999')
        with self.assertRaisesRegex(Refusal, 'Target'):
            self.apply(api)
        self.assertEqual(api.writes, [])

    def test_missing_log_not_silently_recreated(self):
        (self.state / 'ledger.jsonl').unlink()
        api = FakeX()
        with self.assertRaisesRegex(Refusal, 'missing'):
            self.apply(api)
        self.assertEqual(api.calls, [])
        self.assertFalse((self.state / 'ledger.jsonl').exists())

    def test_init_does_not_replace_state(self):
        with self.assertRaises(FileExistsError):
            b.init_state(self.state, OWNER)

    def test_success_records_intent_before_mutation(self):
        api = FakeX()
        def check(method, url, bearer=None, body=None):
            if method != 'GET':
                _, rows = b.read_state(self.state)
                self.assertEqual(rows[-1]['status'], 'intent')
            return api(method, url, bearer, body)
        self.apply(check)
        state, rows = b.read_state(self.state)
        self.assertEqual([row['status'] for row in rows], ['intent', 'confirmed'])
        self.assertEqual(state['count'], 2)
        for path in self.state.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('FAKE_X_TOKEN', (self.state / 'ledger.jsonl').read_text())

    def test_exact_success_endpoint(self):
        api = self.apply()
        self.assertEqual(api.writes, [('POST', 'https://api.x.com/2/users/101/following', {'target_user_id': '202'})])

    def test_partial_graph_blocks_execution(self):
        def partial(*args, **kwargs):
            return deepcopy(self.graph)
        api = FakeX()
        with self.assertRaisesRegex(Refusal, 'complete'):
            self.apply(api, fetch=partial)
        self.assertEqual(api.writes, [])

    def test_apify_partial_snapshot_reconciles_against_complete_x(self):
        self.graph['provider'] = 'apify'
        self.plan['graph_sha256'] = k.digest(self.graph)
        self.assertEqual(len(self.apply().writes), 1)

    def test_current_graph_drift_blocks_execution(self):
        def drift(*args, **kwargs):
            return g.envelope([{'id': '909', 'handle': 'extra'}], OWNER, 'following', 'x', True)
        api = FakeX()
        with self.assertRaisesRegex(Refusal, 'differs'):
            self.apply(api, fetch=drift)
        self.assertEqual(api.writes, [])

    def test_duplicate_execution_blocks_before_api(self):
        self.apply()
        api = FakeX()
        with self.assertRaisesRegex(Refusal, 'already'):
            self.apply(api)
        self.assertEqual(api.calls, [])

    def test_failure_records_unknown_blocks_retry(self):
        api = FakeX(outcome=Refusal('HTTP 429'))
        with self.assertRaisesRegex(Refusal, 'uncertain'):
            self.apply(api)
        self.assertEqual(len(api.writes), 1)
        _, rows = b.read_state(self.state)
        self.assertEqual(rows[-1]['status'], 'unknown')
        retry = FakeX()
        with self.assertRaisesRegex(Refusal, 'unresolved'):
            self.apply(retry)
        self.assertEqual(retry.calls, [])

    def test_all_http_auth_and_rate_failures_stop_without_retry(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                api = FakeX(outcome=Refusal('HTTP ' + str(status)))
                other_state = self.root / str(status)
                with redirect_stdout(io.StringIO()):
                    b.init_state(other_state, OWNER)
                with self.assertRaises(Refusal), redirect_stdout(io.StringIO()):
                    b.apply_plan(self.plan, self.graph, other_state, k.digest(self.plan),
                                 'apply 1 changes from @reader', api=api, fetch=self.fetch)
                self.assertEqual(len(api.writes), 1)
                self.assertEqual(b.read_state(other_state)[1][-1]['status'], 'unknown')

    def test_timeout_stops_before_next_action(self):
        self.plan['actions'].append(dict(self.plan['actions'][0], target_id='303', handle='other'))
        api = FakeX(outcome=TimeoutError())
        def targets(method, url, bearer=None, body=None):
            if '/users/by/username/other' in url:
                api.calls.append((method, url, body))
                return {'data': {'id': '303', 'username': 'other'}}
            return api(method, url, bearer, body)
        with self.assertRaises(Refusal):
            self.apply(targets)
        self.assertEqual(len(api.writes), 1)

    def test_process_lock_refuses_competing_apply_before_api(self):
        import fcntl
        with (self.state / 'batch.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            api = FakeX()
            with self.assertRaises(BlockingIOError):
                self.apply(api)
            self.assertEqual(api.calls, [])

    def test_ledger_symlink_refused(self):
        (self.state / 'ledger.jsonl').unlink()
        other = self.root / 'other-receipt'
        other.write_text('untouched')
        (self.state / 'ledger.jsonl').symlink_to(other)
        api = FakeX()
        with self.assertRaisesRegex(Refusal, 'missing/invalid'):
            self.apply(api)
        self.assertEqual(api.calls, [])
        self.assertEqual(other.read_text(), 'untouched')

    def test_200_with_errors_is_unknown(self):
        api = FakeX(outcome={'data': {'following': True}, 'errors': [{'title': 'problem'}]})
        with self.assertRaises(Refusal):
            self.apply(api)
        self.assertEqual(b.read_state(self.state)[1][-1]['status'], 'unknown')

    def test_pending_stops_and_is_not_undoable(self):
        api = FakeX(outcome={'data': {'following': False, 'pending_follow': True}})
        with self.assertRaisesRegex(Refusal, 'pending'):
            self.apply(api)
        self.assertEqual(b.read_state(self.state)[1][-1]['status'], 'pending')
        with self.assertRaisesRegex(Refusal, 'No confirmed'):
            b.undo_plan(self.state, k.digest(self.plan), self.graph)

    def test_interrupted_intent_blocks_all_future_writes(self):
        state, rows = b.read_state(self.state)
        b.append(self.state, state, rows, {'operation_id': 'lost', 'target_id': '777', 'status': 'intent'})
        api = FakeX()
        with self.assertRaisesRegex(Refusal, 'unresolved'):
            self.apply(api)
        self.assertEqual(api.calls, [])

    def test_torn_or_deleted_receipt_is_detected(self):
        self.apply()
        (self.state / 'ledger.jsonl').write_text('')
        with self.assertRaisesRegex(Refusal, 'checkpoint'):
            b.read_state(self.state)

    def test_rate_pacing_survives_restart(self):
        clock = [__import__('time').time()]
        now = lambda: clock[0]
        self.apply(now=now)
        self.plan['actions'][0].update(target_id='303', handle='other')
        slept = []
        def sleep(seconds):
            slept.append(seconds)
            clock[0] += seconds
        api = FakeX(target='303')
        self.apply(api, now=now, sleep=sleep)
        self.assertEqual(slept, [60])
        self.assertEqual(len(api.writes), 1)

    def test_opposite_churn_requires_specific_undo(self):
        self.apply()
        self.graph = g.envelope([{'id': '202', 'handle': 'builder'}], OWNER, 'following', 'x', True)
        self.plan['graph_sha256'] = k.digest(self.graph)
        self.plan['actions'][0].update(action='unfollow', before_following=True)
        api = FakeX(outcome={'data': {'following': False}})
        with self.assertRaisesRegex(Refusal, 'churn'):
            self.apply(api)
        self.assertEqual(api.calls, [])

    def test_undo_is_separate_inverse_plan_for_confirmed(self):
        original_digest = k.digest(self.plan)
        self.apply()
        graph = g.envelope([{'id': '202', 'handle': 'builder'}], OWNER, 'following', 'x', True)
        inverse = b.undo_plan(self.state, original_digest, graph)
        self.assertEqual(inverse['actions'][0]['action'], 'unfollow')
        self.assertTrue(inverse['actions'][0]['before_following'])
        self.assertEqual(inverse['actions'][0]['undo_of'], original_digest + ':0')
        self.assertNotEqual(k.digest(inverse), original_digest)

    def test_reviewed_undo_can_apply_after_pacing(self):
        original_digest = k.digest(self.plan)
        self.apply()
        self.graph = g.envelope([{'id': '202', 'handle': 'builder'}], OWNER, 'following', 'x', True)
        self.plan = b.undo_plan(self.state, original_digest, self.graph)
        api = FakeX(outcome={'data': {'following': False}})
        future = __import__('time').time() + 61
        self.apply(api, now=lambda: future)
        self.assertEqual(api.writes[-1][0], 'DELETE')
        self.assertEqual(b.read_state(self.state)[1][-1]['status'], 'confirmed')

    def test_stale_graph_blocks_before_api(self):
        self.graph['fetched_at'] = '2020-01-01T00:00:00+00:00'
        self.plan['graph_sha256'] = k.digest(self.graph)
        api = FakeX()
        with self.assertRaisesRegex(Refusal, '15 minutes'):
            self.apply(api)
        self.assertEqual(api.calls, [])

    def test_budget_blocks_before_api(self):
        api = FakeX()
        with self.assertRaisesRegex(Refusal, 'budget'):
            self.apply(api, max_cost_usd=.001)
        self.assertEqual(api.calls, [])

    def test_large_batch_refused(self):
        self.plan['actions'] *= 11
        with self.assertRaisesRegex(Refusal, '1..10'):
            b.preview(self.plan, self.graph)

    def test_graph_import_normalizes_and_never_asserts_completeness(self):
        value = g.import_graph({'complete': True, 'items': [{'id': 202, 'userName': '@Builder'}]}, OWNER, 'following')
        self.assertEqual(value['accounts'], [{'id': '202', 'handle': 'builder'}])
        self.assertFalse(value['complete'])

    def test_true_jsonl_import_and_json_envelope_mislabeled_jsonl(self):
        rows = [{'id': '202', 'username': 'Builder'}, {'id': '303', 'userName': 'Other'}]
        sources = [('\n'.join(json.dumps(row) for row in rows) + '\n'),
                   json.dumps({'items': rows, 'complete': True})]
        for i, text in enumerate(sources):
            with self.subTest(source=i):
                source = self.root / f'input-{i}.jsonl'
                source.write_text(text)
                output = self.root / f'output-{i}.json'
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(g.main(['import', '--input', str(source), '--kind', 'following',
                                              '--user-id', '101', '--handle', 'reader', '--output', str(output)]), 0)
                imported = k.load(output)
                self.assertEqual(len(imported['accounts']), 2)
                self.assertFalse(imported['complete'])

    def test_malformed_mixed_jsonl_never_writes_partial_graph(self):
        source = self.root / 'bad.jsonl'
        output = self.root / 'partial.json'
        for text in ('{"id":"202","username":"builder"}\nnot-json\n',
                     '{"id":"202","username":"builder"}\n["unexpected"]\n',
                     '{"id":"202","username":"builder"}\n{"id":"303","username":"bad\x1b"}\n'):
            source.write_text(text)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(g.main(['import', '--input', str(source), '--kind', 'following',
                                          '--user-id', '101', '--handle', 'reader', '--output', str(output)]), 2)
            self.assertFalse(output.exists())

    def test_single_account_jsonl_pilot_imports(self):
        source = self.root / 'one.jsonl'
        source.write_text('{"id":"202","username":"Builder"}\n')
        imported = g.import_graph(g.load_import(source), OWNER, 'following')
        self.assertEqual(imported['accounts'], [{'id': '202', 'handle': 'builder'}])
        self.assertFalse(imported['complete'])

    def test_graph_x_paginated_complete(self):
        calls = []
        def api(method, url, bearer):
            calls.append(url)
            if len(calls) == 1:
                return {'data': [{'id': '202', 'username': 'Builder'}], 'meta': {'next_token': 'next'}}
            return {'data': [{'id': '303', 'username': 'Other'}], 'meta': {}}
        value = g.x_graph(OWNER, 'following', 3, 1, api, 'fake')
        self.assertTrue(value['complete'])
        self.assertEqual(len(value['accounts']), 2)
        self.assertIn('pagination_token=next', calls[1])

    def test_graph_x_cap_is_incomplete(self):
        value = g.x_graph(OWNER, 'following', 1, 1,
                          lambda *args: {'data': [{'id': '202', 'username': 'Builder'}], 'meta': {'next_token': 'n'}}, 'fake')
        self.assertFalse(value['complete'])

    def test_graph_duplicate_pages_cannot_claim_completeness(self):
        with self.assertRaisesRegex(Refusal, 'duplicate'):
            g.x_graph(OWNER, 'following', 3, 1,
                      lambda *args: {'data': [{'id': '202', 'username': 'builder'}], 'meta': {'next_token': 'next'}}, 'fake')

    def test_graph_budget_prevents_request(self):
        with self.assertRaisesRegex(Refusal, 'budget'):
            g.x_graph(OWNER, 'following', 1000, 1, lambda *args: self.fail('no network'), 'fake')

    def test_bad_or_conflicting_ids_refused(self):
        for rows in ([{'id': 'oops', 'username': 'builder'}], [{'id': '2', 'username': 'a'}, {'id': '2', 'username': 'b'}]):
            with self.assertRaises(Refusal):
                k.normalize_people(rows)

    def test_default_fetch_and_search_zero_network(self):
        with patch.object(g, 'http', side_effect=AssertionError('no network')), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(g.main(['fetch', '--provider', 'x', '--kind', 'following', '--user-id', '101',
                                      '--handle', 'reader', '--output', str(self.root / 'g.json')]), 0)
        self.assertIn('"network_calls": 0', out.getvalue())
        with patch.object(af, 'http', side_effect=AssertionError('no network')), redirect_stdout(io.StringIO()):
            self.assertEqual(af.main(['search', '--query', 'enterprise AI', '--output', str(self.root / 'p.json')]), 0)
        self.assertFalse((self.root / 'g.json').exists())
        self.assertFalse((self.root / 'p.json').exists())

    def test_oauth_batch_tool_preserves_ephemeral_token_flow(self):
        with patch.dict(os.environ, {'X_CLIENT_ID': 'public-client-id'}), \
                patch.object(oauth, 'obtain_token', return_value='FAKE_EPHEMERAL_TOKEN'), \
                patch.object(oauth.subprocess, 'run') as child:
            child.return_value.returncode = 0
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(oauth.main(['--login', '--tool', 'batch', '--', 'preview', '--plan', 'p.json', '--graph', 'g.json']), 0)
            args, kwargs = child.call_args
            self.assertTrue(args[0][1].endswith('/batch.py'))
            self.assertEqual(kwargs['env']['X_USER_ACCESS_TOKEN'], 'FAKE_EPHEMERAL_TOKEN')
            self.assertNotIn('FAKE_EPHEMERAL_TOKEN', ' '.join(args[0]) + out.getvalue())

    def test_oauth_tool_selection_default_remains_offline(self):
        with patch.object(oauth, 'obtain_token', side_effect=AssertionError('network')), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(oauth.main(['--tool', 'batch', '--', 'apply']), 0)
        self.assertIn('0 network calls', out.getvalue())

    def make_uncertain(self):
        operation_id = k.digest(self.plan) + ':0'
        with self.assertRaises(Refusal):
            self.apply(FakeX(outcome=TimeoutError()))
        return operation_id

    def reconcile(self, operation_id, outcome='not-applied', api=None, **kwargs):
        _, _, _, review = b.reconciliation_review(self.state, operation_id, outcome, self.graph)
        api = api or FakeX()
        with redirect_stdout(io.StringIO()):
            b.reconcile_operation(self.state, operation_id, outcome, self.graph, k.digest(review),
                                  f'reconcile {operation_id} as {outcome} from @reader', api=api,
                                  fetch=kwargs.pop('fetch', self.fetch), **kwargs)
        return api

    def test_reconcile_preview_zero_network_and_no_new_record(self):
        operation = self.make_uncertain()
        before = (self.state / 'ledger.jsonl').read_text()
        with redirect_stdout(io.StringIO()) as output:
            b.preview_reconciliation(self.state, operation, 'not-applied', self.graph)
        self.assertIn('"network_calls": 0', output.getvalue())
        self.assertEqual(before, (self.state / 'ledger.jsonl').read_text())

    def test_reconcile_not_applied_preserves_history_and_sends_no_write(self):
        operation = self.make_uncertain()
        api = self.reconcile(operation)
        _, rows = b.read_state(self.state)
        self.assertEqual([row['status'] for row in rows], ['intent', 'unknown', 'not_applied'])
        self.assertTrue(rows[-1]['reconciled'])
        self.assertEqual(rows[-1]['user_approved_outcome'], 'not-applied')
        self.assertEqual(api.writes, [])
        with self.assertRaisesRegex(Refusal, 'No confirmed'):
            b.undo_plan(self.state, k.digest(self.plan), self.graph)

    def test_reconcile_not_applied_allows_only_new_reviewed_plan(self):
        operation = self.make_uncertain()
        self.reconcile(operation)
        with self.assertRaisesRegex(Refusal, 'already'):
            self.apply()
        self.plan['created_at'] = k.stamp()
        self.plan['actions'][0]['reason'] = 'Reviewed again after the user verified that no change occurred.'
        api = self.apply(now=lambda: __import__('time').time() + 61)
        self.assertEqual(len(api.writes), 1)

    def test_reconcile_completed_is_undoable_after_explicit_approval(self):
        original_batch = k.digest(self.plan)
        operation = self.make_uncertain()
        self.graph = g.envelope([{'id': '202', 'handle': 'builder'}], OWNER, 'following', 'x', True)
        api = self.reconcile(operation, outcome='completed')
        self.assertEqual(api.writes, [])
        _, rows = b.read_state(self.state)
        self.assertEqual(rows[-1]['status'], 'confirmed')
        self.assertEqual(rows[-1]['user_approved_outcome'], 'completed')
        inverse = b.undo_plan(self.state, original_batch, self.graph)
        self.assertEqual(inverse['actions'][0]['undo_of'], operation)

    def test_reconcile_wrong_authenticated_account_refused(self):
        operation = self.make_uncertain()
        api = FakeX(source='999')
        with self.assertRaisesRegex(Refusal, 'account mismatch'):
            self.reconcile(operation, api=api)
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(b.read_state(self.state)[1][-1]['status'], 'unknown')

    def test_reconcile_target_mismatch_refused(self):
        operation = self.make_uncertain()
        api = FakeX(target='999')
        with self.assertRaisesRegex(Refusal, 'Target identity'):
            self.reconcile(operation, api=api)
        self.assertEqual(api.writes, [])
        self.assertEqual(b.read_state(self.state)[1][-1]['status'], 'unknown')

    def test_reconcile_wrong_expected_state_refused(self):
        operation = self.make_uncertain()
        with self.assertRaisesRegex(Refusal, 'chosen'):
            self.reconcile(operation, outcome='completed')

    def test_reconcile_stale_snapshot_refused_before_api(self):
        operation = self.make_uncertain()
        self.graph['fetched_at'] = '2020-01-01T00:00:00+00:00'
        api = FakeX()
        with self.assertRaisesRegex(Refusal, '15 minutes'):
            self.reconcile(operation, api=api)
        self.assertEqual(api.calls, [])

    def test_reconcile_complete_fresh_snapshot_mismatch_refused(self):
        operation = self.make_uncertain()
        def mismatch(*args, **kwargs):
            return g.envelope([{'id': '909', 'handle': 'extra'}], OWNER, 'following', 'x', True)
        api = FakeX()
        with self.assertRaisesRegex(Refusal, 'Fresh complete'):
            self.reconcile(operation, api=api, fetch=mismatch)
        self.assertEqual(api.writes, [])
        self.assertEqual(b.read_state(self.state)[1][-1]['status'], 'unknown')

    def test_reconcile_requires_matching_review_digest_and_confirmation(self):
        operation = self.make_uncertain()
        api = FakeX()
        with self.assertRaisesRegex(Refusal, 'digest'):
            b.reconcile_operation(self.state, operation, 'not-applied', self.graph, 'wrong', 'yes', api=api)
        self.assertEqual(api.calls, [])

    def test_reconcile_cannot_resolve_confirmed_operation_again(self):
        operation = self.make_uncertain()
        self.reconcile(operation)
        with self.assertRaisesRegex(Refusal, 'already resolved'):
            self.reconcile(operation)

    def test_reconcile_pending_requires_user_chosen_actual_outcome(self):
        operation = k.digest(self.plan) + ':0'
        with self.assertRaisesRegex(Refusal, 'pending'):
            self.apply(FakeX(outcome={'data': {'following': False, 'pending_follow': True}}))
        self.assertEqual(b.read_state(self.state)[1][-1]['status'], 'pending')
        self.graph = g.envelope([{'id': '202', 'handle': 'builder'}], OWNER, 'following', 'x', True)
        self.reconcile(operation, outcome='completed')
        self.assertEqual(b.read_state(self.state)[1][-1]['status'], 'confirmed')


class ApifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / 'result.json'
        self.env = patch.dict(os.environ, {'APIFY_TOKEN': 'FAKE_APIFY_TOKEN'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.calls = []
        self.prices = {'data': {'pricingInfo': {'pricingModel': 'PAY_PER_EVENT', 'pricingPerEvent': {
            'actorChargeEvents': {'apify-default-dataset-item': {'eventPriceUsd': .0004}}}}}}

    def api(self, method, url, bearer=None, body=None):
        self.calls.append((method, url, bearer, body))
        if '/acts/' in url and method == 'GET':
            return self.prices
        if method == 'POST':
            return {'data': {'id': 'run123'}}
        if '/actor-runs/' in url:
            return {'data': {'id': 'run123', 'status': 'SUCCEEDED', 'defaultDatasetId': 'data123', 'usageTotalUsd': .0004}}
        return [{'id': 'post1', 'text': 'Synthetic public post.'}]

    def run_actor(self, **kwargs):
        return af.run_actor('apidojo~tweet-scraper', {'searchTerms': ['enterprise AI'], 'maxItems': 1, 'sort': 'Latest'},
                            1, .05, self.output, api=kwargs.pop('api', self.api), sleep=lambda _: None, **kwargs)

    def test_live_price_server_cap_and_settled_receipt(self):
        result = self.run_actor()
        post = next(call for call in self.calls if call[0] == 'POST')
        self.assertIn('maxTotalChargeUsd=0.05', post[1])
        self.assertEqual(result['settled_cost_usd'], .0004)
        self.assertEqual(len(result['items']), 1)
        receipt = Path(str(self.output) + '.run.json')
        self.assertNotIn('FAKE_APIFY_TOKEN', receipt.read_text())
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)

    def test_current_pricingInfos_and_tiered_prices(self):
        current = {'pricingModel': 'PAY_PER_EVENT', 'startedAt': '2026-06-09T15:21:49.332Z',
                   'pricingPerEvent': {'actorChargeEvents': {'apify-default-dataset-item': {
                       'eventTieredPricingUsd': {'FREE': {'tieredEventPriceUsd': .0004},
                                                'BRONZE': {'tieredEventPriceUsd': .0003}}}}}}
        self.prices = {'data': {'pricingInfos': [dict(current, startedAt='2099-01-01T00:00:00Z'), current]}}
        result = self.run_actor()
        self.assertEqual(result['settled_cost_usd'], .0004)

    def test_graph_query_and_profile_costs_included(self):
        prices = {'pricingInfo': {'pricingModel': 'PAY_PER_EVENT', 'pricingPerEvent': {'actorChargeEvents': {
            'dataset-item': {'eventPriceUsd': .0004}, 'following-event': {'eventPriceUsd': .016},
            'follower-event': {'eventPriceUsd': .016}, 'single-url-event': {'eventPriceUsd': .004},
            'about-event': {'eventPriceUsd': .0002}}}}}
        ceiling, _ = af.pricing_ceiling('apidojo~twitter-user-scraper', prices, 100,
                                        {'getFollowing': True})
        self.assertAlmostEqual(ceiling, .06)

    def test_unknown_billing_event_refused(self):
        self.prices['data']['pricingInfo']['pricingPerEvent']['actorChargeEvents']['new-charge'] = {'eventPriceUsd': 0}
        with self.assertRaisesRegex(Refusal, 'changed'):
            self.run_actor()

    def test_resume_only_original_id_never_posts(self):
        first = self.run_actor()
        self.calls.clear()
        resumed = self.run_actor(resume_run_id=first['run_id'])
        self.assertEqual(first['items'], resumed['items'])
        self.assertTrue(all(call[0] == 'GET' for call in self.calls))

    def test_unknown_pricing_refused_before_post(self):
        self.prices = {'data': {'pricingInfo': {}}}
        with self.assertRaisesRegex(Refusal, 'pricing'):
            self.run_actor()
        self.assertTrue(all(call[0] == 'GET' for call in self.calls))

    def test_price_increase_refused(self):
        self.prices['data']['pricingInfo']['pricingPerEvent']['actorChargeEvents']['apify-default-dataset-item']['eventPriceUsd'] = 5
        with self.assertRaisesRegex(Refusal, 'exceeds'):
            self.run_actor()

    def test_start_timeout_receipt_prevents_resubmit(self):
        def fail(method, *args, **kwargs):
            if method == 'POST':
                raise Refusal('transport timeout')
            return self.api(method, *args, **kwargs)
        with self.assertRaises(Refusal):
            self.run_actor(api=fail)
        self.assertEqual(k.load(Path(str(self.output) + '.run.json'))['status'], 'start_intent')
        with self.assertRaisesRegex(Refusal, 'already exists'):
            self.run_actor()
        self.assertFalse(any(call[0] == 'POST' for call in self.calls))

    def test_duplicate_completed_run_refused(self):
        self.run_actor()
        before = len(self.calls)
        with self.assertRaisesRegex(Refusal, 'already exists'):
            self.run_actor()
        self.assertEqual(len(self.calls), before)

    def test_actor_allowlist(self):
        with self.assertRaisesRegex(Refusal, 'allowlist'):
            af.run_actor('unknown~actor', {}, 1, .05, self.output)


if __name__ == '__main__':
    unittest.main()
