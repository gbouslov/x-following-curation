#!/usr/bin/env python3
"""Fetch public account graphs with an explicit read budget; offline by default."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlencode

from kit_common import account, digest, http, load, normalize_people, report_error, save, stamp, token
from relationships import Refusal


def envelope(people, owner, kind, provider, complete=False, retrieval=None):
    if kind not in ('following', 'followers'):
        raise Refusal('Graph kind must be following or followers.')
    return {'version': 1, 'provider': provider, 'kind': kind, 'account': owner,
            'fetched_at': stamp(), 'complete': complete, 'accounts': normalize_people(people),
            'retrieval': retrieval or {}}


def validate_graph(value):
    if not isinstance(value, dict) or value.get('version') != 1:
        raise Refusal('Expected a version 1 graph object.')
    owner = value.get('account', {})
    if not isinstance(owner, dict):
        raise Refusal('Graph account must be an object.')
    account(owner.get('id'), owner.get('handle'))
    if value.get('kind') not in ('following', 'followers') or type(value.get('complete')) is not bool:
        raise Refusal('Graph kind or completeness is invalid.')
    normalized = normalize_people(value.get('accounts'))
    if normalized != value['accounts']:
        raise Refusal('Graph accounts must be normalized and unique; import the source first.')
    return value


def x_graph(owner, kind, max_items, max_cost_usd, api=http, bearer=None):
    # Budget conservatively at the standard $.01/resource, including repeated pages.
    if not 1 <= max_items <= 100_000 or not 0 < max_cost_usd <= 100:
        raise Refusal('Use 1..100000 max-items and a positive budget no larger than $100.')
    bearer = bearer or token('X_USER_ACCESS_TOKEN')
    rows, seen_tokens, cursor = [], set(), None
    seen_ids = set()
    pages, requested = 0, 0
    complete = False
    while len(rows) < max_items:
        size = min(1000, max_items - len(rows))
        if (requested + size) * .01 > max_cost_usd + 1e-9:
            raise Refusal('Conservative X graph budget would be exceeded; no next request sent.')
        params = {'max_results': size, 'user.fields': 'username'}
        if cursor:
            params['pagination_token'] = cursor
        value = api('GET', 'https://api.x.com/2/users/' + owner['id'] + '/' + kind + '?' + urlencode(params), bearer)
        pages += 1
        if not isinstance(value, dict) or value.get('errors'):
            raise Refusal('X graph returned errors; cannot establish complete coverage.')
        data = value.get('data', [])
        if not isinstance(data, list) or len(data) > size:
            raise Refusal('Unexpected X graph page size or response shape.')
        requested += len(data)
        normalized = normalize_people(data)
        ids = {person['id'] for person in normalized}
        if len(normalized) != len(data) or ids & seen_ids:
            raise Refusal('Graph pagination returned duplicate IDs; refresh before claiming complete coverage.')
        rows.extend(normalized)
        seen_ids.update(ids)
        meta = value.get('meta')
        if not isinstance(meta, dict):
            raise Refusal('X graph pagination metadata is missing.')
        cursor = meta.get('next_token')
        if not cursor:
            complete = True
            break
        if not isinstance(cursor, str) or cursor in seen_tokens or not data or pages >= 10_000:
            raise Refusal('X pagination repeated or made no progress; coverage is incomplete.')
        seen_tokens.add(cursor)
    return envelope(rows, owner, kind, 'x', complete, {
        'pages': pages, 'max_items': max_items, 'max_cost_usd': max_cost_usd,
        'budget_basis_usd_per_resource': .01, 'returned_resources_counted': requested,
        'next_token_present': bool(cursor)})


def import_graph(value, owner, kind):
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict):
        rows = next((value[k] for k in ('accounts', 'items', 'data') if isinstance(value.get(k), list)), None)
        if rows is None and any(key in value for key in ('id', 'userId', 'rest_id')):
            rows = [value]  # A one-line JSONL pilot is also one valid whole JSON account object.
    else:
        rows = None
    return envelope(rows, owner, kind, 'import', False, {'coverage': 'unverified import'})


def load_import(path):
    # Historical .jsonl files may actually be one JSON run envelope. Content wins over suffix.
    with Path(path).open('rb') as stream:
        raw = stream.read(25_000_001)
    if len(raw) > 25_000_000:
        raise Refusal('Graph import exceeds 25 MB; split the source first.')
    text = raw.decode('utf-8-sig')
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        rows = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                raise Refusal('Malformed JSON/JSONL import; no partial graph was written.') from None
            if not isinstance(row, dict):
                raise Refusal('JSONL import requires one account object per nonempty line.')
            rows.append(row)
        if not rows:
            raise Refusal('Graph import is empty or malformed.')
        return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('fetch', 'import'):
        p = commands.add_parser(command)
        p.add_argument('--kind', choices=['following', 'followers'], required=True)
        p.add_argument('--user-id', required=True)
        p.add_argument('--handle', required=True)
        p.add_argument('--output', type=Path, required=True)
        if command == 'import':
            p.add_argument('--input', type=Path, required=True)
        else:
            p.add_argument('--provider', choices=['x', 'apify'], required=True)
            p.add_argument('--max-items', type=int, default=100)
            p.add_argument('--max-cost-usd', type=float, default=1)
            p.add_argument('--execute', action='store_true')
            p.add_argument('--resume-run-id')
    args = parser.parse_args(argv)
    try:
        owner = account(args.user_id, args.handle)
        if args.command == 'import':
            result = import_graph(load_import(args.input), owner, args.kind)
        elif not args.execute:
            if not 1 <= args.max_items <= 100_000 or not 0 < args.max_cost_usd <= 100:
                raise Refusal('Invalid retrieval size or budget.')
            if args.provider == 'apify' and (args.max_items > 10_000 or args.max_cost_usd > 1):
                raise Refusal('Apify supports at most 10000 items and an approved cap no larger than $1.')
            print(json.dumps({'dry_run': True, 'network_calls': 0, 'provider': args.provider,
                              'kind': args.kind, 'account': owner, 'max_items': args.max_items,
                              'max_cost_usd': args.max_cost_usd,
                              'x_graph_standard_ceiling_usd': args.max_items * .01 if args.provider == 'x' else None}))
            return 0
        elif args.provider == 'x':
            if args.resume_run_id:
                raise Refusal('Resume run IDs apply only to Apify.')
            result = x_graph(owner, args.kind, args.max_items, args.max_cost_usd)
        else:
            from apify_fetch import run_actor
            actor_input = {'twitterHandles': [owner['handle']], 'maxItems': args.max_items,
                           'getFollowing': args.kind == 'following', 'getFollowers': args.kind == 'followers'}
            receipt = run_actor('apidojo~twitter-user-scraper', actor_input, args.max_items,
                                args.max_cost_usd, args.output, args.resume_run_id)
            result = envelope(receipt['items'], owner, args.kind, 'apify', False, {
                k: v for k, v in receipt.items() if k != 'items'})
        save(args.output, result)
        print(json.dumps({'output': str(args.output), 'count': len(result['accounts']),
                          'complete': result['complete'], 'sha256': digest(result)}))
        return 0
    except (Refusal, OSError, ValueError, TypeError, KeyError) as exc:
        print('STOP: ' + report_error(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
