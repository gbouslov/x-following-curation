---
name: x-pull-graph
description: Retrieves following and followers separately through X API v2, capped Apify retrieval or a local export. Use before classifying an existing feed or checking approved changes.
---

<objective>
Know who the user actually follows, with a dated, countable snapshot and honest coverage. Followers describe the audience; following determines this cleanup. Never mix them.
</objective>
<quick_start>
Read `references/capabilities.md`, `references/api-and-safety.md` and `references/session-files.md`. Check `python3 scripts/graph.py --help` and its fetch/import help. Defaults preview without networking. Use the exact ID and handle of the intended account.
</quick_start>
<process>
1. Read local/goals.md. Establish current handle, numeric ID and chosen provider. Show the route, maximum returned accounts, price estimate, per-run cap and remaining session budget. User approval of the cost precedes `--execute`. Protected accounts and missing access are coverage gaps; do not borrow browser cookies or rotate tokens.
2. Fetch following and followers into separate local files, for example `python3 scripts/graph.py fetch --provider apify --kind following --user-id USER_ID --handle HANDLE --max-items 1000 --max-cost-usd 0.50 --output local/following.json`. Preview first; repeat with --execute only when approved. Change kind/output for followers. The tools normalize ID/handle, deduplicate and retain retrieval metadata. Apify data is public retrieval; actor completion does not prove full graph coverage.
3. For X, choose --provider x with an approved budget that covers returned resources at the conservative standard rate. Page until no next_token; mark incomplete if capped or interrupted. For an existing export use `graph.py import --input PATH --kind following --user-id USER_ID --handle HANDLE --output local/following.json`. Imported graphs remain unverified/incomplete until reconciled; never silently declare full coverage.
4. Compare unique IDs with the current account counter where available and inspect pagination/cap/duplicate/errors. Store the fetched_at, provider, graph hash and observed gap in local/session.md. Count discrepancies are real gaps, not an excuse to invent missing people. Never overwrite a previous run without preserving it. A failed paid start may have created a run: recover its receipt/run ID rather than starting again.
5. Report following and follower counts separately, complete or partial, price cap and settled spend. Keep all IDs/private graph membership local. Classify the available following rows with x-classify; clearly name any missing rows. Before an apply, obtain the helper's fresh complete authenticated X graph check and reconcile every ID; an unverified partial export cannot authorize changes.
</process>
<success_criteria>
Both relations have independent snapshots and counts. Every fetched account is traceable to its source; completeness is backed by pagination/count reconciliation. The agent reports partial coverage and actual cost honestly, no secret or private graph leaves the user's session, and no relationship changes occurred.
</success_criteria>
