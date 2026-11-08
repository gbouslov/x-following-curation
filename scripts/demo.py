#!/usr/bin/env python3
"""Replay an agent-authored fictional session. No network, keys or real X writes."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

from batch import apply_plan, init_state, preview, read_state, undo_plan
from graph import envelope, x_graph
from kit_common import digest


def main():
    root = Path(__file__).resolve().parents[1]
    source = json.loads((root / 'examples/session/fixture.json').read_text())
    owner = source['account']
    people = {p['id']: p for p in source['following'] + source['discovery']}
    following = {p['id'] for p in source['following']}
    judgments = source['classification']
    assert len(judgments) == len(following) == len({p['id'] for p in judgments})
    assert {p['id'] for p in judgments} == following
    posts = {p['id']: p for p in source['posts']}
    assert all(posts[pid]['author_id'] == person['id']
               for person in judgments + source['discovery'] for pid in person['post_ids'])
    epoch = [datetime.now(timezone.utc).timestamp()]
    writes = []

    def clock():
        return epoch[0]

    def sleep(seconds):
        epoch[0] += seconds

    def capture():
        graph = envelope([people[uid] for uid in following], owner, 'following', 'fixture', True)
        graph['fetched_at'] = datetime.fromtimestamp(clock(), timezone.utc).isoformat()
        return graph

    def api(method, url, bearer=None, body=None):
        path = urlsplit(url).path
        if method == 'GET' and path == '/2/users/me':
            return {'data': {'id': owner['id'], 'username': owner['handle']}}
        if method == 'GET' and path.startswith('/2/users/by/username/'):
            person = next(p for p in people.values() if p['handle'] == path.rsplit('/', 1)[1])
            return {'data': {'id': person['id'], 'username': person['handle']}}
        if method == 'GET' and path == '/2/users/100/following':
            return {'data': [{'id': uid, 'username': people[uid]['handle']} for uid in sorted(following)],
                    'meta': {'result_count': len(following)}}
        if method == 'POST' and path == '/2/users/100/following':
            following.add(body['target_user_id'])
            writes.append(('follow', body['target_user_id'], clock()))
            return {'data': {'following': True, 'pending_follow': False}}
        if method == 'DELETE' and path.startswith('/2/users/100/following/'):
            uid = path.rsplit('/', 1)[1]
            following.remove(uid)
            writes.append(('unfollow', uid, clock()))
            return {'data': {'following': False}}
        raise AssertionError('Unexpected simulated API route')

    before = capture()
    plan = {'version': 1, 'account': owner, 'created_at': before['fetched_at'],
            'graph_sha256': digest(before), 'actions': copy.deepcopy(source['approved_actions'])}
    print('OFFLINE FICTIONAL SESSION: 3 classified follows, 1 discovered creator; 0 real network calls.')
    print('Goals: repeatable delivery, acquisition diligence and enterprise AI value.')
    approved = preview(plan, before)
    # The token function is replaced; the real process environment is never consulted.
    with tempfile.TemporaryDirectory(prefix='xkit-demo-') as temp:
        state = Path(temp) / 'receipts'
        init_state(state, owner)
        with patch('socket.create_connection', side_effect=AssertionError('Network forbidden in demo')), \
                patch('batch.token', return_value='offline-placeholder'):
            apply_plan(plan, before, state, approved, 'apply 2 changes from @reader_demo',
                       api=api, fetch=x_graph, now=clock, sleep=sleep)
        after = capture()
        assert following == {'201', '203', '204'}
        assert len(writes) == 2 and writes[1][2] - writes[0][2] >= 60
        _, receipts = read_state(state)
        assert [r['status'] for r in receipts] == ['intent', 'confirmed', 'intent', 'confirmed']
        inverse = undo_plan(state, approved, after)
        assert {(a['target_id'], a['action']) for a in inverse['actions']} == {('202', 'follow'), ('204', 'unfollow')}
        print('SIMULATED RESULT: keeper/contact preserved; two confirmed changes; 60-second pacing checked.')
        print('UNDO PREVIEW ONLY (no inverse writes):')
        with patch('batch.time.time', side_effect=clock):
            preview(inverse, after)
    print('PASS: goals -> complete classification -> discovery -> preview -> simulated apply -> undo preview.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
