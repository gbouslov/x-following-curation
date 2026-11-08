#!/usr/bin/env python3
"""Offline bulk preview; one explicitly confirmed X API v2 relationship change.

Python 3.10+, macOS/Linux. No third-party packages. No credential files read.
"""
import argparse
import csv
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

API = 'https://api.x.com/2'
HANDLE = re.compile(r'^[A-Za-z0-9_]{1,15}$')
ID = re.compile(r'^[0-9]{1,19}$')


class Refusal(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Refusal('Unexpected API redirect; no redirect followed.')


def request(method, path, token, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = Request(API + path, data=data, method=method, headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with build_opener(NoRedirect).open(req, timeout=25) as response:
            value = json.loads(response.read(1_000_000))
    except HTTPError as exc:
        reset = exc.headers.get('x-rate-limit-reset', 'not supplied')
        if not str(reset).isdigit():
            reset = 'not supplied'
        raise Refusal(f'HTTP {exc.code}; stopped without retry. Rate reset epoch: {reset}.') from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise Refusal('API transport or response failure; stopped without retry. Check account state manually.') from None
    if not isinstance(value, dict):
        raise Refusal('Unexpected API response; check account state manually.')
    return value


def handle(value):
    if not isinstance(value, str):
        raise Refusal('Missing or invalid handle in input.')
    result = value.removeprefix('@')
    if not HANDLE.fullmatch(result):
        raise Refusal('Invalid handle; use a current X username, not a URL.')
    return result


def preview(args):
    if args.target:
        handles = [handle(args.target)]
    else:
        with args.csv.open(newline='', encoding='utf-8-sig') as stream:
            rows = list(csv.DictReader(stream))
        if not rows or any('handle' not in row for row in rows):
            raise Refusal('CSV needs a handle column and at least one row.')
        handles = [handle(row['handle']) for row in rows]
    seen = set()
    for value in handles:
        if value.lower() not in seen:
            print(f'DRY RUN: {args.action} @{value} — https://x.com/{value}')
            seen.add(value.lower())
    print(f'{len(seen)} unique planned actions; 0 network calls, 0 changes. Bulk plans cannot execute.')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def append_receipt(path, row):
    # Fail before a mutation if the local audit log cannot be appended.
    fd = private_fd(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    with os.fdopen(fd, 'a') as stream:
        stream.write(json.dumps(row, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def private_fd(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise Refusal('Receipt and lock paths must be regular files, never links or devices.')
    os.fchmod(fd, 0o600)
    return fd


def execute(args, api=request):
    if not args.target:
        raise Refusal('Bulk execution is disabled. Review the CSV, then choose one --target.')
    target = handle(args.target)
    if not args.expected_user_id or not ID.fullmatch(args.expected_user_id):
        raise Refusal('Provide your own verified numeric --expected-user-id.')
    if not args.expected_username:
        raise Refusal('Provide your own --expected-username.')
    expected_name = handle(args.expected_username)
    phrase = f'{args.action} @{target} from @{expected_name}'
    if args.confirm != phrase:
        raise Refusal('Explicit confirmation required: --confirm ' + repr(phrase))
    token = os.environ.get('X_USER_ACCESS_TOKEN', '')
    if not token or any(c.isspace() for c in token):
        raise Refusal('Set X_USER_ACCESS_TOKEN to your own OAuth user access token. Never paste it into chat.')
    args.log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = private_fd(str(args.log) + '.lock', os.O_CREAT | os.O_RDWR)
    with os.fdopen(lock_fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rows = []
        with os.fdopen(private_fd(args.log, os.O_RDONLY | os.O_CREAT), 'r') as receipt:
            rows = [json.loads(line) for line in receipt if line.strip()]
        me = api('GET', '/users/me', token)
        actor = me.get('data') or {}
        if (me.get('errors') or not isinstance(actor, dict) or str(actor.get('id')) != args.expected_user_id
                or actor.get('username', '').lower() != expected_name.lower()):
            raise Refusal('Authenticated account does not match expected ID and username; no change.')
        result = api('GET', '/users/by/username/' + target, token)
        person = result.get('data') or {}
        if not isinstance(person, dict):
            raise Refusal('Unexpected target response; no change.')
        target_id = str(person.get('id', ''))
        if (result.get('errors') or not ID.fullmatch(target_id)
                or person.get('username', '').lower() != target.lower()):
            raise Refusal('Target lookup failed or handle changed; no change.')
        if target_id == args.expected_user_id:
            raise Refusal('Self-target refused.')
        prior = [r for r in rows if r.get('source_id') == args.expected_user_id
                 and r.get('target_id') == target_id]
        if prior:
            last = prior[-1]
            if last.get('status') in ('intent', 'unknown'):
                raise Refusal('Earlier outcome is unresolved. Inspect the profile before any retry; use the website.')
            if last.get('action') == args.action and last.get('status') in ('confirmed', 'pending'):
                raise Refusal('This action is already recorded. Inspect the profile; no duplicate request sent.')
        writes = [r for r in rows if r.get('source_id') == args.expected_user_id and r.get('status') == 'intent']
        if writes and time.time() - float(writes[-1]['epoch']) < 60:
            raise Refusal('Local 60-second minimum interval has not elapsed. This is not an X policy allowance.')
        base = {'time': stamp(), 'epoch': time.time(), 'source_id': args.expected_user_id,
                'target_id': target_id, 'target': target, 'action': args.action}
        append_receipt(args.log, dict(base, status='intent'))
        try:
            if args.action == 'follow':
                response = api('POST', f'/users/{args.expected_user_id}/following', token,
                               {'target_user_id': target_id})
            else:
                response = api('DELETE', f'/users/{args.expected_user_id}/following/{target_id}', token)
            data = response.get('data') or {}
            if response.get('errors') or not isinstance(data, dict):
                raise Refusal('API reported errors; outcome unresolved. Inspect the profile.')
            if args.action == 'follow' and data.get('pending_follow') is True:
                status = 'pending'
            elif data.get('following') is (args.action == 'follow'):
                status = 'confirmed'
            else:
                raise Refusal('API did not confirm the expected relationship. Inspect the profile.')
        except Exception:
            append_receipt(args.log, dict(base, status='unknown', time=stamp()))
            raise
        append_receipt(args.log, dict(base, status=status, time=stamp()))
        print(f'API {status}: {args.action} @{target}. Check https://x.com/{target} in your account.')
        print(f'Private receipt: {args.log}')


def _default_log():
    """Receipts live outside Git. Keep using the pre-rename directory if it already holds receipts."""
    state = Path.home() / '.local/state'
    legacy = state / 'x-operator-kit/operations.jsonl'
    return legacy if legacy.exists() else state / 'x-following-curation/operations.jsonl'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--csv', type=Path, default=Path(__file__).resolve().parents[1] / 'follow-set.csv')
    group.add_argument('--target')
    parser.add_argument('--action', choices=['follow', 'unfollow'], default='follow')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--dry-run', action='store_true', help='Default: no network or changes')
    parser.add_argument('--expected-user-id')
    parser.add_argument('--expected-username')
    parser.add_argument('--confirm')
    parser.add_argument('--log', type=Path, default=_default_log())
    args = parser.parse_args(argv)
    try:
        if args.execute:
            execute(args)
        else:
            preview(args)
    except (Refusal, OSError, ValueError, KeyError):
        # Do not dump request objects, raw provider bodies or token-bearing tracebacks.
        exc = sys.exc_info()[1]
        print('STOP: ' + (str(exc) if isinstance(exc, Refusal) else 'Local input/log failure; no retry. Inspect files.'), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
