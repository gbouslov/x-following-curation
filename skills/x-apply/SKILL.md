---
name: x-apply
description: Previews, validates and applies an exact user-approved batch of X follows and unfollows with pacing, durable receipts and a separately approved undo path. Use only after account review and target selection.
---

<objective>
Carry out the user's chosen feed changes through their own X user-context API, at a pace they can inspect, with no silent retries or unlogged changes.
</objective>
<quick_start>
Read `references/api-and-safety.md`, `references/session-files.md` and `references/capabilities.md`. Run `python3 scripts/batch.py --help`, then preview/apply subcommand help. Use fictional fixtures with `python3 scripts/demo.py` before any live operation.
</quick_start>
<essential_principles>
Default is offline preview. The agent cannot supply approval on the user's behalf. Plan/digest/account/cost must match what the user approved. Maximum ten actions per batch, minimum 60 seconds between writes, no automatic follow churn. Policy and account restrictions still apply. Never loop around a refusal or rotate credentials to evade a limit.
</essential_principles>
<process>
1. From selected classification/discovery rows write local/plan.json with the exact account ID/handle, current UTC created_at, graph_sha256 and actions (target ID/handle, follow or unfollow, specific reason, before_following boolean). Follow requires false, unfollow true. Exclude every unapproved, uncertain, protected-sensitive or pinned target. Use a fresh following snapshot and preserve previous plans.
2. Run `python3 scripts/batch.py preview --plan local/plan.json --graph local/following.json`. Show every row, account, count, digest, snapshot age and estimated retrieval/write cost. Obtain the user's explicit approval for that exact list and budget; no account write before it. Any row/account/reason/graph edit changes the digest and requires new approval. Split larger sets into separately approved batches.
3. Initialize a private state directory with `batch.py init-state` only for genuinely new state; never bypass a missing/corrupt log by initializing elsewhere. The apply helper verifies /users/me, re-fetches the complete following list, matches IDs against the supplied snapshot and resolves each handle to its numeric ID. Refuse stale plans or state drift and return to preview. Never assume Apify/export metadata alone proves the live relationship.
4. Only after approval, run `batch.py apply` with --execute, the matching --digest, exact --confirm phrase and approved --max-cost-usd. The helper logs intent before each write, locks state, paces attempts, validates semantic outcomes and records results. Stop on errors, unknown/partial responses or pending follow requests. Do not repeat an unresolved operation. Inspect the actual relationship, then use `batch.py reconcile` with a fresh graph and user-approved completed/not-applied outcome, resolution digest and account phrase. Reconciliation verifies current state and appends a receipt without sending a follow/unfollow. Do not print tokens or raw error bodies.
5. Re-pull the graph when its read cost is approved, compare expected and observed relationships and record any gap. Report succeeded, pending, failed and untouched separately. For reversal use `batch.py undo` with the original digest and a fresh graph; this writes an inverse plan from confirmed successes only. Preview it and obtain separate user approval before applying. It cannot retract notifications, guarantee access to a private account or undo unrelated intervening changes.
</process>
<success_criteria>
Every attempted mutation belongs to the exact approved plan and has durable secret-free intent/result records. Outcomes are verified, unknown results never auto-retry, and inverse actions are reviewable rather than automatically executed. Unchanged or unapproved targets remain untouched.
</success_criteria>
