#!/usr/bin/env python3
"""Review exact agent-written plans; apply small approved batches with durable receipts."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import sys
import time

from graph import validate_graph, x_graph
from kit_common import account, digest, http, load, report_error, save, stamp, token
from relationships import Refusal, private_fd

ZERO = '0' * 64


def validate_plan(plan, graph):
    validate_graph(graph)
    if not isinstance(plan, dict) or plan.get('version') != 1:
        raise Refusal('Expected a version 1 plan object.')
    owner = plan.get('account', {})
    if not isinstance(owner, dict):
        raise Refusal('Plan account must be an object.')
    normalized = account(owner.get('id'), owner.get('handle'))
    if normalized != owner or owner != graph['account'] or graph['kind'] != 'following':
        raise Refusal('Plan and following graph accounts must match exactly.')
    if plan.get('graph_sha256') != digest(graph):
        raise Refusal('Plan graph_sha256 does not match the reviewed graph.')
    try:
        created = datetime.fromisoformat(plan['created_at'])
        if created.tzinfo is None:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise Refusal('Plan requires a timezone-aware created_at timestamp.') from None
    actions = plan.get('actions')
    if not isinstance(actions, list) or not 1 <= len(actions) <= 10:
        raise Refusal('A reviewed batch must contain 1..10 actions.')
    following = {p['id'] for p in graph['accounts']}
    seen = set()
    names = set()
    for action in actions:
        if not isinstance(action, dict):
            raise Refusal('Plan action must be an object.')
        person = account(action.get('target_id'), action.get('handle'))
        if person['handle'] != action['handle']:
            raise Refusal('Use normalized lowercase target handles.')
        if person['id'] == owner['id'] or person['id'] in seen or person['handle'] in names:
            raise Refusal('Self-targets and duplicate targets are refused.')
        seen.add(person['id'])
        names.add(person['handle'])
        before = action.get('before_following')
        desired = action.get('action')
        if type(before) is not bool or desired not in ('follow', 'unfollow') or before == (desired == 'follow'):
            raise Refusal('Action must change the explicit boolean before_following state.')
        if before != (person['id'] in following):
            raise Refusal('Action before_following does not match the reviewed graph.')
        reason = action.get('reason')
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000 or any(ord(c) < 32 for c in reason):
            raise Refusal('Each action needs a printable agent-written reason of 1..1000 characters.')
    return plan


def preview(plan, graph):
    validate_plan(plan, graph)
    try:
        fetched = datetime.fromisoformat(graph['fetched_at'])
        if fetched.tzinfo is None:
            raise ValueError()
        snapshot_age = round(time.time() - fetched.timestamp(), 3)
    except (KeyError, TypeError, ValueError):
        raise Refusal('Graph requires a timezone-aware fetched_at timestamp.') from None
    for action in plan['actions']:
        print(json.dumps({k: action[k] for k in ('target_id', 'handle', 'action', 'before_following', 'reason')}, ensure_ascii=True))
    value = digest(plan)
    print(json.dumps({'dry_run': True, 'network_calls': 0, 'actions': len(plan['actions']),
                      'account': plan['account'], 'sha256': value, 'graph_sha256': digest(graph),
                      'graph_fetched_at': graph['fetched_at'], 'graph_snapshot_age_seconds': snapshot_age,
                      'graph_complete': graph['complete'], 'graph_account_count': len(graph['accounts']),
                      'confirm': f"apply {len(plan['actions'])} changes from @{plan['account']['handle']}"}))
    return value


def init_state(root, owner):
    root = Path(root)
    # Explicitly initialize a NEW state directory. Never recreate a missing ledger in an old one.
    root.mkdir(mode=0o700)
    os.chmod(root, 0o700)
    save(root / 'state.json', {'version': 1, 'account': owner, 'head': ZERO, 'count': 0}, exclusive=True)
    fd = private_fd(root / 'ledger.jsonl', os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.fsync(fd)
    os.close(fd)
    print('Initialized private batch state. Preserve this directory; never replace missing receipts with fresh state.')


def read_state(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise Refusal('State directory is missing or a link. Explicit init-state is required for first use.')
    os.chmod(root, 0o700)
    for name in ('state.json', 'ledger.jsonl'):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise Refusal('State or receipt file is missing/invalid. Restore the original; do not reinitialize.')
        os.chmod(path, 0o600)
    state = load(root / 'state.json')
    if not isinstance(state, dict):
        raise Refusal('Private state is not an object; no mutation allowed.')
    rows = []
    head = ZERO
    with (root / 'ledger.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            if not line.endswith('\n'):
                raise Refusal('Truncated ledger entry; restore/reconcile state before another write.')
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise Refusal('Invalid receipt entry; no mutation allowed.')
            row = entry.get('record')
            if entry.get('previous') != head or entry.get('sha256') != digest({'previous': head, 'record': row}):
                raise Refusal('Receipt chain mismatch; no mutation allowed.')
            head = entry['sha256']
            rows.append(row)
    if state.get('version') != 1 or state.get('head') != head or state.get('count') != len(rows):
        raise Refusal('Receipt checkpoint mismatch; no mutation allowed.')
    owner = state.get('account', {})
    if not isinstance(owner, dict):
        raise Refusal('State account must be an object.')
    account(owner.get('id'), owner.get('handle'))
    return state, rows


def append(root, state, rows, row):
    entry = {'previous': state['head'], 'record': row}
    entry['sha256'] = digest(entry)
    fd = private_fd(Path(root) / 'ledger.jsonl', os.O_WRONLY | os.O_APPEND)
    with os.fdopen(fd, 'a') as stream:
        stream.write(json.dumps(entry, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    state.update(head=entry['sha256'], count=state['count'] + 1)
    save(Path(root) / 'state.json', state)
    rows.append(row)


def latest_operations(rows):
    latest = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('status') not in ('intent', 'confirmed', 'pending', 'unknown', 'not_applied'):
            raise Refusal('Unexpected ledger record; no mutation allowed.')
        latest[row['operation_id']] = row
    return latest


def apply_plan(plan, graph, root, approved_digest, confirm, max_cost_usd=1,
               api=http, fetch=x_graph, now=time.time, sleep=time.sleep):
    validate_plan(plan, graph)
    batch_digest = digest(plan)
    phrase = f"apply {len(plan['actions'])} changes from @{plan['account']['handle']}"
    if approved_digest != batch_digest or confirm != phrase:
        raise Refusal('Exact plan digest and explicit account confirmation are required.')
    if not math.isfinite(max_cost_usd) or not 0 < max_cost_usd <= 100:
        raise Refusal('Set an approved positive X cap no larger than $100.')
    # Require a recent reviewed snapshot. Fresh complete API graph is still mandatory below.
    try:
        age = now() - datetime.fromisoformat(graph['fetched_at']).timestamp()
        plan_age = now() - datetime.fromisoformat(plan['created_at']).timestamp()
    except (KeyError, TypeError, ValueError):
        raise Refusal('Graph/plan timestamp missing or invalid.') from None
    if not 0 <= age <= 900 or not 0 <= plan_age <= 900:
        raise Refusal('Reviewed graph and plan must be no older than 15 minutes; refresh and approve again.')
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise Refusal('Private state missing; never initialize state silently.')
    fd = private_fd(root / 'batch.lock', os.O_CREAT | os.O_RDWR)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state, rows = read_state(root)
        if state['account'] != plan['account']:
            raise Refusal('Private state belongs to a different account.')
        latest = latest_operations(rows)
        if any(row['status'] not in ('confirmed', 'not_applied') for row in latest.values()):
            raise Refusal('An earlier intent/pending/unknown result is unresolved. Inspect X; no retry.')
        for i, action in enumerate(plan['actions']):
            if batch_digest + ':' + str(i) in latest:
                raise Refusal('This batch has already been attempted; never replay a partial batch.')
            prior = [row for row in latest.values() if row['target_id'] == action['target_id'] and row['status'] != 'not_applied']
            undo_id = action.get('undo_of')
            if prior and not (undo_id and prior[-1]['operation_id'] == undo_id
                    and prior[-1]['action'] != action['action'] and prior[-1]['status'] == 'confirmed'):
                raise Refusal('Target has a prior write. Repeated/opposite churn is refused; use a reviewed undo plan.')
            if undo_id and (not prior or prior[-1]['operation_id'] != undo_id):
                raise Refusal('Undo reference does not match the latest confirmed target operation.')
        # One self lookup, target lookups, and mutation charges. Graph capped separately.
        overhead = .01 * (1 + len(plan['actions'])) + sum(.015 if a['action'] == 'follow' else .010 for a in plan['actions'])
        graph_items = max(1, len(graph['accounts']) + 1)
        if overhead + graph_items * .01 > max_cost_usd + 1e-9:
            raise Refusal('Conservative complete-graph/lookups/writes estimate exceeds the approved X budget.')
        bearer = token('X_USER_ACCESS_TOKEN')
        me = api('GET', 'https://api.x.com/2/users/me', bearer)
        person = me.get('data', {}) if isinstance(me, dict) else {}
        if not isinstance(me, dict) or not isinstance(person, dict) or me.get('errors') or account(person.get('id'), person.get('username')) != plan['account']:
            raise Refusal('Authenticated account mismatch; no write.')
        fresh = fetch(plan['account'], 'following', graph_items, max_cost_usd - overhead, api=api, bearer=bearer)
        if fresh.get('complete') is not True or {p['id'] for p in fresh['accounts']} != {p['id'] for p in graph['accounts']}:
            raise Refusal('Current complete following graph differs from the reviewed snapshot; no write.')
        for action in plan['actions']:
            result = api('GET', 'https://api.x.com/2/users/by/username/' + action['handle'], bearer)
            person = result.get('data', {}) if isinstance(result, dict) else {}
            if not isinstance(result, dict) or not isinstance(person, dict) or result.get('errors') or account(person.get('id'), person.get('username')) != account(action['target_id'], action['handle']):
                raise Refusal('Target ID or handle mismatch; no write.')
        for i, action in enumerate(plan['actions']):
            intents = [row for row in rows if row['status'] == 'intent']
            if intents:
                elapsed = now() - intents[-1]['epoch']
                if elapsed < 0:
                    raise Refusal('Local clock moved backwards; inspect state before continuing.')
                if elapsed < 60:
                    sleep(60 - elapsed)
                    if now() - intents[-1]['epoch'] < 60:
                        raise Refusal('60-second write interval has not elapsed.')
            row = {'operation_id': batch_digest + ':' + str(i), 'batch_digest': batch_digest,
                   'source_id': plan['account']['id'], 'target_id': action['target_id'],
                   'handle': action['handle'], 'action': action['action'], 'before_following': action['before_following'],
                   'epoch': now(), 'time': stamp(), 'status': 'intent'}
            if action.get('undo_of'):
                row['undo_of'] = action['undo_of']
            append(root, state, rows, row)
            try:
                base = 'https://api.x.com/2/users/' + plan['account']['id'] + '/following'
                result = api('POST', base, bearer, {'target_user_id': action['target_id']}) if action['action'] == 'follow' else api('DELETE', base + '/' + action['target_id'], bearer)
                data = result.get('data', {}) if isinstance(result, dict) else {}
                if not isinstance(data, dict) or result.get('errors'):
                    raise Refusal('API returned errors; mutation outcome unresolved.')
                if action['action'] == 'follow' and data.get('pending_follow') is True:
                    status = 'pending'
                elif data.get('following') is (action['action'] == 'follow'):
                    status = 'confirmed'
                else:
                    raise Refusal('API did not confirm expected relationship state.')
            except Exception:
                append(root, state, rows, dict(row, status='unknown', time=stamp()))
                raise Refusal('Write failed or outcome is uncertain. Stop; inspect X and receipts. No retry.') from None
            append(root, state, rows, dict(row, status=status, time=stamp()))
            print(json.dumps({'target_id': action['target_id'], 'handle': action['handle'], 'status': status}))
            if status != 'confirmed':
                raise Refusal('Follow is pending; batch stopped. Inspect the protected account before continuing.')


def reconciliation_review(root, operation_id, outcome, graph):
    validate_graph(graph)
    state, rows = read_state(root)
    if outcome not in ('completed', 'not-applied'):
        raise Refusal('Explicitly choose completed or not-applied after inspecting the actual account.')
    if graph['account'] != state['account'] or graph['kind'] != 'following':
        raise Refusal('Reconciliation graph belongs to a different account or graph kind.')
    latest = latest_operations(rows)
    row = latest.get(operation_id)
    if not row or row['status'] not in ('intent', 'unknown', 'pending'):
        raise Refusal('Operation is missing or already resolved; nothing to reconcile.')
    if row.get('source_id') != state['account']['id']:
        raise Refusal('Operation account does not match private state.')
    account(row.get('target_id'), row.get('handle'))
    if type(row.get('before_following')) is not bool or row.get('action') not in ('follow', 'unfollow'):
        raise Refusal('Original operation metadata is incomplete; no automatic repair is available.')
    expected = row['action'] == 'follow' if outcome == 'completed' else row['before_following']
    current = row['target_id'] in {p['id'] for p in graph['accounts']}
    if current != expected:
        raise Refusal('Reviewed graph does not match the explicitly chosen reconciliation outcome.')
    review = {'operation_id': operation_id, 'outcome': outcome, 'account': state['account'],
              'target_id': row['target_id'], 'handle': row['handle'],
              'expected_following': expected, 'graph_sha256': digest(graph)}
    return state, rows, row, review


def preview_reconciliation(root, operation_id, outcome, graph):
    _, _, _, review = reconciliation_review(root, operation_id, outcome, graph)
    phrase = f"reconcile {operation_id} as {outcome} from @{review['account']['handle']}"
    print(json.dumps(dict(review, dry_run=True, network_calls=0, sha256=digest(review), confirm=phrase)))
    print('Inspect the real account first. A pending request must be completed or cancelled before choosing an outcome.')
    return digest(review)


def reconcile_operation(root, operation_id, outcome, graph, approved_digest, confirm,
                        max_cost_usd=1, api=http, fetch=x_graph, now=time.time):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise Refusal('Private state is missing; restore it before reconciliation.')
    fd = private_fd(root / 'batch.lock', os.O_CREAT | os.O_RDWR)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state, rows, row, review = reconciliation_review(root, operation_id, outcome, graph)
        phrase = f"reconcile {operation_id} as {outcome} from @{state['account']['handle']}"
        if approved_digest != digest(review) or confirm != phrase:
            raise Refusal('Exact reconciliation digest and explicit outcome/account confirmation are required.')
        try:
            age = now() - datetime.fromisoformat(graph['fetched_at']).timestamp()
            original_epoch = row['epoch']
            if not isinstance(original_epoch, (int, float)) or not math.isfinite(original_epoch):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise Refusal('Graph or operation time is invalid; no receipt changed.') from None
        if not 0 <= age <= 900 or now() < original_epoch:
            raise Refusal('Reconciliation needs a graph no older than 15 minutes and a consistent clock.')
        if not math.isfinite(max_cost_usd) or not 0 < max_cost_usd <= 100:
            raise Refusal('Set an approved positive X read cap no larger than $100.')
        graph_items = max(1, len(graph['accounts']) + 1)
        overhead = .02  # authenticated account and exact-target lookups
        if graph_items * .01 + overhead > max_cost_usd + 1e-9:
            raise Refusal('Reconciliation complete-graph/lookups estimate exceeds the approved read budget.')
        bearer = token('X_USER_ACCESS_TOKEN')
        me = api('GET', 'https://api.x.com/2/users/me', bearer)
        person = me.get('data', {}) if isinstance(me, dict) else None
        if (not isinstance(me, dict) or me.get('errors') or not isinstance(person, dict)
                or account(person.get('id'), person.get('username')) != state['account']):
            raise Refusal('Authenticated account mismatch; no receipt changed.')
        fresh = fetch(state['account'], 'following', graph_items, max_cost_usd - overhead, api=api, bearer=bearer)
        if (fresh.get('complete') is not True
                or {p['id'] for p in fresh['accounts']} != {p['id'] for p in graph['accounts']}):
            raise Refusal('Fresh complete following graph does not match the reviewed reconciliation snapshot.')
        result = api('GET', 'https://api.x.com/2/users/by/username/' + row['handle'], bearer)
        person = result.get('data', {}) if isinstance(result, dict) else None
        if (not isinstance(result, dict) or result.get('errors') or not isinstance(person, dict)
                or account(person.get('id'), person.get('username')) != account(row['target_id'], row['handle'])):
            raise Refusal('Target identity changed; no receipt changed.')
        # The human supplies semantic outcome; graph matching alone never declares a write successful.
        resolved = dict(row, status='confirmed' if outcome == 'completed' else 'not_applied',
                        reconciled=True, user_approved_outcome=outcome, reconciled_at=stamp(),
                        reconciliation_sha256=digest(review), reconciliation_graph_sha256=digest(graph))
        append(root, state, rows, resolved)
        print(json.dumps({'operation_id': operation_id, 'status': resolved['status'],
                          'reconciled': True, 'x_writes': 0}))


def undo_plan(root, batch_digest, graph):
    validate_graph(graph)
    state, rows = read_state(root)
    if graph['account'] != state['account'] or graph['kind'] != 'following':
        raise Refusal('Undo needs the same account following graph.')
    latest = latest_operations(rows)
    following = {p['id'] for p in graph['accounts']}
    actions = []
    for row in latest.values():
        if row.get('batch_digest') != batch_digest or row['status'] != 'confirmed':
            continue
        if any(other.get('undo_of') == row['operation_id'] and other['status'] != 'not_applied'
               for other in latest.values()):
            continue
        before = row['action'] == 'follow'
        if (row['target_id'] in following) != before:
            raise Refusal('Undo snapshot does not match confirmed outcomes; refresh and inspect.')
        actions.append({'target_id': row['target_id'], 'handle': row['handle'],
                        'action': 'unfollow' if before else 'follow', 'before_following': before,
                        'reason': 'Restore the previous relationship from a confirmed operation; review before applying.',
                        'undo_of': row['operation_id']})
    if not actions:
        raise Refusal('No confirmed, unreversed operations in that batch.')
    plan = {'version': 1, 'account': state['account'], 'created_at': stamp(),
            'graph_sha256': digest(graph), 'actions': actions}
    return validate_plan(plan, graph)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('init-state')
    p.add_argument('--state-dir', type=Path, required=True)
    p.add_argument('--user-id', required=True)
    p.add_argument('--handle', required=True)
    for command in ('preview', 'apply'):
        p = sub.add_parser(command)
        p.add_argument('--plan', type=Path, required=True)
        p.add_argument('--graph', type=Path, required=True)
        if command == 'apply':
            p.add_argument('--state-dir', type=Path, required=True)
            p.add_argument('--execute', action='store_true')
            p.add_argument('--digest')
            p.add_argument('--confirm')
            p.add_argument('--max-cost-usd', type=float, default=1)
    p = sub.add_parser('undo')
    p.add_argument('--state-dir', type=Path, required=True)
    p.add_argument('--batch-digest', required=True)
    p.add_argument('--graph', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('reconcile')
    p.add_argument('--state-dir', type=Path, required=True)
    p.add_argument('--operation-id', required=True)
    p.add_argument('--outcome', choices=['completed', 'not-applied'], required=True)
    p.add_argument('--graph', type=Path, required=True)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--digest')
    p.add_argument('--confirm')
    p.add_argument('--max-cost-usd', type=float, default=1)
    args = parser.parse_args(argv)
    try:
        if args.command == 'init-state':
            init_state(args.state_dir, account(args.user_id, args.handle))
        elif args.command == 'reconcile':
            graph = load(args.graph)
            if args.execute:
                reconcile_operation(args.state_dir, args.operation_id, args.outcome, graph,
                                    args.digest, args.confirm, args.max_cost_usd)
            else:
                preview_reconciliation(args.state_dir, args.operation_id, args.outcome, graph)
        elif args.command == 'undo':
            plan = undo_plan(args.state_dir, args.batch_digest, load(args.graph))
            save(args.output, plan, exclusive=True)
            preview(plan, load(args.graph))
            print('Inverse plan only: preview and obtain separate exact approval. Protected refollows may be pending.')
        else:
            plan, graph = load(args.plan), load(args.graph)
            if args.command == 'apply' and args.execute:
                apply_plan(plan, graph, args.state_dir, args.digest, args.confirm, args.max_cost_usd)
            else:
                preview(plan, graph)
        return 0
    except (Refusal, OSError, ValueError, TypeError, KeyError) as exc:
        print('STOP: ' + report_error(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
