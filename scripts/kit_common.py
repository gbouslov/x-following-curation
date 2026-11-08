"""Deterministic local I/O and HTTP helpers. Never reads credential stores."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from relationships import NoRedirect, Refusal, handle, ID, stamp


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def account(user_id, username):
    if not isinstance(user_id, str) or not ID.fullmatch(user_id):
        raise Refusal('Numeric user IDs must be strings.')
    return {'id': user_id, 'handle': handle(username).lower()}


def load(path):
    path = Path(path)
    if path.stat().st_size > 25_000_000:
        raise Refusal('Local JSON exceeds 25 MB; split the input first.')
    with path.open(encoding='utf-8') as stream:
        return json.load(stream)


def save(path, value, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Refusal('Output must be a regular file, never a link or device.')
    raw = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n'
    if exclusive:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        fd, temp = tempfile.mkstemp(prefix='.xkit-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def token(name):
    value = os.environ.get(name, '')
    if not value or any(c.isspace() for c in value):
        raise Refusal('Set ' + name + ' privately in your environment.')
    return value


def http(method, url, bearer=None, body=None):
    if not (url.startswith('https://api.apify.com/v2/') or url.startswith('https://api.x.com/2/')):
        raise Refusal('Unapproved API origin.')
    headers = {'Content-Type': 'application/json'}
    if bearer:
        headers['Authorization'] = 'Bearer ' + bearer
    req = Request(url, method=method, headers=headers,
                  data=None if body is None else json.dumps(body).encode())
    try:
        with build_opener(NoRedirect).open(req, timeout=25) as response:
            raw = response.read(10_000_001)
            if len(raw) > 10_000_000:
                raise Refusal('API response too large; stopped without retry.')
            return json.loads(raw)
    except HTTPError as exc:
        raise Refusal('API HTTP ' + str(exc.code) + '; stopped without retry.') from None
    except (URLError, OSError, ValueError):
        raise Refusal('API transport or response failure; stopped without retry.') from None


def normalize_people(rows):
    if not isinstance(rows, list):
        raise Refusal('Graph requires an array of account objects.')
    people = {}
    handles = {}
    for row in rows:
        if not isinstance(row, dict):
            raise Refusal('Graph account is not an object.')
        uid = row.get('id') or row.get('userId') or row.get('rest_id')
        if isinstance(uid, int) and not isinstance(uid, bool):
            uid = str(uid)
        username = row.get('handle') or row.get('username') or row.get('userName') or row.get('screen_name')
        person = account(uid, username)
        old = people.get(uid)
        if old and old != person:
            raise Refusal('Conflicting handles for one ID in graph.')
        if person['handle'] in handles and handles[person['handle']] != uid:
            raise Refusal('One handle maps to multiple IDs in graph.')
        people[uid] = person
        handles[person['handle']] = uid
    return sorted(people.values(), key=lambda p: int(p['id']))


def report_error(exc):
    return str(exc) if isinstance(exc, Refusal) else 'Local input or state failure; inspect private files. No retry.'
