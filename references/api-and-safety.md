# API setup, previews and approved changes

Run commands from repo root. Replace uppercase placeholders with your own verified identifiers and approved budgets. Never put an access token in a command argument, chat or plan. See [capabilities](capabilities.md) for prices and access, and [session files](session-files.md) for schemas.

## Authentication

Set your own APIFY_TOKEN and/or X_USER_ACCESS_TOKEN privately in the terminal environment. Tools do not inspect browser sessions, keychains, auth stores or .env files. If you keep a project .env, load it privately yourself.

The optional OAuth helper supports a public Native App, Authorization Code + PKCE (S256), callback state validation and a localhost listener. Register exactly `http://127.0.0.1:8765/callback` in your app, enable OAuth 2.0 and set X_CLIENT_ID privately. Requested scopes: tweet.read users.read follows.read follows.write. It prints an authorization URL, never the token, and stores no refresh token. Open the URL yourself and verify the account/app. Login and its reads need approval; login does not approve account changes.

```bash
python3 scripts/oauth_session.py --dry-run
# After approval of login and the account lookup cost:
python3 scripts/oauth_session.py --login --whoami
```

A short-lived token can be passed to one bundled child tool via its environment:

```bash
python3 scripts/oauth_session.py --login --tool graph -- fetch \
  --provider x --kind following --user-id USER_ID --handle HANDLE \
  --max-items 1000 --max-cost-usd 11 --output local/following.json --execute
```

Use --tool batch similarly for batch operations; default relationships retains the v1 single-target helper. The selector cannot run an arbitrary shell command. Revoke unneeded app access in X's connected-app settings. [PKCE documentation](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code), [authentication mapping](https://docs.x.com/fundamentals/authentication/guides/v2-authentication-mapping).

## Retrieval preview

These defaults make zero network calls and need no credentials:

```bash
python3 scripts/graph.py fetch --provider apify --kind following \
  --user-id USER_ID --handle HANDLE --max-items 1000 \
  --max-cost-usd 0.50 --output local/following.json
python3 scripts/apify_fetch.py search --query 'enterprise AI implementation since:2026-09-01' \
  --max-items 50 --max-cost-usd 0.05 --output local/topic-posts.json
```

Show individual caps and aggregate session budget before adding --execute. The runner rechecks all active actor charge events and sets server-side maxTotalChargeUsd. Unknown pricing refuses the run. Start with a small pilot. Followers use a separate --kind followers job and output. X uses --provider x with a cap sufficient for standard-rate resources, up to the explicit $100 tool ceiling; no owned discount is assumed.

Imports use `graph.py import --input EXPORT --kind following --user-id USER_ID --handle HANDLE --output local/following.json`. Import cannot prove completeness. Preserve the run receipt next to a paid output on interruption. Recover the existing run ID and use --resume-run-id ID with the same request; never automatically submit another paid run. See script help for receipt handling.

## Exact plan approval

The agent writes a plan using the session-files schema, then previews every action:

```bash
python3 scripts/batch.py preview --plan local/plan.json --graph local/following.json
```

The user approves the displayed account, targets, actions, reasons, digest and budget. Maximum ten actions per batch. Editing the plan or graph requires a new preview and approval. For genuinely new state initialize once:

```bash
python3 scripts/batch.py init-state --state-dir "$HOME/.x-operator-state" \
  --user-id USER_ID --handle HANDLE
```

Preserve that directory. Never initialize elsewhere to bypass missing, corrupt or unresolved receipts. After exact-list approval, privately set X_USER_ACCESS_TOKEN and run:

```bash
python3 scripts/batch.py apply --plan local/plan.json --graph local/following.json \
  --state-dir "$HOME/.x-operator-state" --execute --digest APPROVED_SHA256 \
  --confirm 'apply N changes from @HANDLE' --max-cost-usd APPROVED_BUDGET
```

Replace N and HANDLE with the preview's exact values. The PKCE alternative is `oauth_session.py --login --tool batch -- apply ...` with the same arguments. Default apply without --execute only previews.

The helper verifies /users/me, fetches complete fresh following pages, reconciles all IDs against the snapshot and resolves every target handle to its numeric ID. Plan and snapshot must be at most 15 minutes old. Cost includes graph reads, source/target lookups and mutations. An Apify/imported graph can proceed only if that complete fresh X graph reconciles; any gap refuses writes.

POST /2/users/{id}/following uses target_user_id; DELETE /2/users/{id}/following/{target_id} removes it. A process lock protects the private state. Each intent is fsynced before its request and each result afterward. Attempts are at least 60 seconds apart. This state directory cannot enforce pacing for the website, legacy helper or other clients; do not interleave them. Prior-target protections refuse churn, with reviewed undo as the explicit exception.

## Outcomes, reconciliation and reversal

Following=true confirms a follow, following=false confirms an unfollow. Pending requests stop the batch. HTTP success alone is insufficient. Errors, 401/403/429, transport failures, identity mismatch, graph drift and missing receipts stop execution. Never rerun a partial batch's digest. Inspect the actual account and reconcile unresolved outcomes before preparing a fresh approved plan for untouched actions.

An unresolved attempt blocks later writes. After inspecting the actual relationship, obtain a fresh graph with an approved read budget and preview an explicit resolution:

```bash
python3 scripts/batch.py reconcile --state-dir "$HOME/.x-operator-state" \
  --operation-id ORIGINAL_SHA256:INDEX --outcome completed --graph local/current.json
```

Choose completed only when the desired relationship now exists; choose not-applied only when the original relationship remains. The helper does not infer the answer on your behalf. Approve the displayed resolution digest and confirmation, then repeat with --execute --digest REVIEW_SHA and the exact --confirm phrase, plus --max-cost-usd for its verification reads. The helper verifies /users/me, the complete current graph, target identity and expected state before appending a reconciled receipt. It sends no follow/unfollow. Pending requests must first reach a known state; no pending request is silently declared complete. Preserve all old receipts. Not-applied permits a newly reviewed plan; it never permits replaying the original batch digest. Missing/corrupt state requires restoring the original receipts, not reconciliation against a replacement directory.

With a newly approved read budget, obtain local/after.json and compare expected relationships. Prepare inverse actions from confirmed successes:

```bash
python3 scripts/batch.py undo --state-dir "$HOME/.x-operator-state" \
  --batch-digest ORIGINAL_SHA256 --graph local/after.json --output local/undo.json
python3 scripts/batch.py preview --plan local/undo.json --graph local/after.json
```

Undo prepares a plan only. Review and approve it separately before apply. It cannot retract notifications, guarantee private-account acceptance or reverse unrelated changes. Pending/unknown outcomes are not confirmed successes.

V1 dry-run commands remain compatible. V2 uses batch.py for exact-list operations. All tests and the demo are offline; live OAuth, paid retrieval and X writes were not exercised while building the kit.
