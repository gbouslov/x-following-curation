#!/usr/bin/env python3
"""Optional ephemeral OAuth PKCE session. Default is a no-network preview.

Register a public Native App with callback http://127.0.0.1:8765/callback.
Reads X_CLIENT_ID from your environment. Never prints or saves access tokens.
"""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener

from relationships import NoRedirect, Refusal, request

CALLBACK = 'http://127.0.0.1:8765/callback'
SCOPES = 'tweet.read users.read follows.read follows.write'


def obtain_token(client_id):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    received = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Query contains the authorization code: never log it.

        def do_GET(self):
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            valid = (parts.path == '/callback' and query.get('state') == [state])
            code = query.get('code', [''])[0]
            self.send_response(200 if valid else 400)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b'Return to the terminal.' if valid else b'Invalid callback; return to terminal.')
            if valid:
                received['code'] = code
                received['error'] = bool(query.get('error')) or not code

    with HTTPServer(('127.0.0.1', 8765), Callback) as server:
        server.timeout = 0.5
        url = 'https://x.com/i/oauth2/authorize?' + urlencode({
            'response_type': 'code', 'client_id': client_id, 'redirect_uri': CALLBACK,
            'scope': SCOPES, 'state': state, 'code_challenge': challenge,
            'code_challenge_method': 'S256'})
        print('Open this authorization URL in your browser; review the app and account:', flush=True)
        print(url, flush=True)
        deadline = time.monotonic() + 180
        while not received and time.monotonic() < deadline:
            server.handle_request()
    if not received or received.get('error'):
        raise Refusal('Authorization declined or timed out. No token saved and no relationship changed.')
    body = urlencode({'code': received['code'], 'grant_type': 'authorization_code',
                      'client_id': client_id, 'redirect_uri': CALLBACK,
                      'code_verifier': verifier}).encode()
    req = Request('https://api.x.com/2/oauth2/token', data=body,
                  headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
    try:
        with build_opener(NoRedirect).open(req, timeout=25) as response:
            result = json.loads(response.read(100_000))
    except Exception:
        raise Refusal('Token exchange failed; check the app type and exact callback. No token saved.') from None
    token = result.get('access_token')
    granted = set(result.get('scope', '').split())
    if not token or not set(SCOPES.split()).issubset(granted):
        raise Refusal('Token response lacks the requested access; no relationship changed.')
    return token


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--login', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    parser.add_argument('--whoami', action='store_true', help='After explicit login, display your own handle and numeric ID')
    parser.add_argument('--tool', choices=['relationships', 'batch', 'graph'], default='relationships',
                        help='Bundled child tool; receives the temporary token only through its environment')
    parser.add_argument('relationship_args', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.login:
        print('DRY RUN: OAuth disabled; 0 network calls. Explicit --login enables a 180-second local callback.')
        return 0
    try:
        client_id = os.environ.get('X_CLIENT_ID', '')
        if not client_id or any(c.isspace() for c in client_id):
            raise Refusal('Set your own public Native App X_CLIENT_ID in the environment first.')
        token = obtain_token(client_id)
        if args.whoami:
            value = request('GET', '/users/me', token)
            data = value.get('data') or {}
            if value.get('errors') or not data.get('username') or not data.get('id'):
                raise Refusal('Could not verify your account; no relationship changed.')
            print(f"Authenticated as @{data['username']} (numeric ID {data['id']}). No relationship changed.")
            return 0
        rest = args.relationship_args
        if rest and rest[0] == '--':
            rest = rest[1:]
        if not rest:
            raise Refusal('Supply --whoami or relationship arguments after --. No token saved.')
        env = dict(os.environ, X_USER_ACCESS_TOKEN=token)
        return subprocess.run([sys.executable, str(Path(__file__).with_name(args.tool + '.py')), *rest],
                              env=env, check=False).returncode
    except (Refusal, OSError):
        exc = sys.exc_info()[1]
        print('STOP: ' + (str(exc) if isinstance(exc, Refusal) else 'Local callback could not start; check port 8765.'), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
