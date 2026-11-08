# Files in your private session

Run all commands from the repository root. Store working files under ignored `local/`; never stage them. State receipts belong in a private directory outside the checkout. Schema examples use fictional people and IDs.

## From goals to a reviewable plan

| File | Who writes it | Contents |
| --- | --- | --- |
| source-manifest.md, goals.md | Agent | Approved source scope, decision questions, preferences, exceptions and public search terms |
| following.json, followers.json | Graph helper | Separate normalized snapshots, capture time, provider, coverage and IDs |
| posts.json, discovery-q*.json | Retrieval helper | Original posts, author IDs, dates, URLs and retrieval receipts |
| classification.csv, discovery.csv | Agent | Specific account judgments and source links |
| plan.json | Agent | Only selected actions, bound to a reviewed snapshot |
| session.md, reading.md, monthly/*.md | Agent | Coverage, spend, useful observations, outcomes and next step |

Graph schema:

```json
{
  "version": 1,
  "provider": "fixture",
  "kind": "following",
  "account": {"id": "100", "handle": "reader_demo"},
  "fetched_at": "2026-10-27T17:00:00+00:00",
  "complete": true,
  "accounts": [{"id": "201", "handle": "operator_demo"}],
  "retrieval": {"network_calls": 0}
}
```

Helpers emit the canonical JSON SHA-256, not a hash of the file's whitespace. Import leaves complete=false. The literal fixture shown here cannot prove live relationships. Apply verifies a fresh complete X snapshot and compares every numeric ID, regardless of the supplied provider label.

Classification CSV columns:

```text
id,handle,decision,reason,relevance,firsthand,signal,contribution,sample_count,sample_start,sample_end,post_urls,exception
```

Decision is keep/review/unfollow. The agent reads posts and assigns four 0–3 scores. Put multiple post URLs in a single quoted field. Exception identifies pins, contacts or deliberate counterviews; blank otherwise. Review can have sample_count=0 with a clear gap. Proposed unfollows need actual representative posts and no unresolved exception. Counts alone cannot validate the quality of a judgment.

Discovery CSV adds pool, goal_gap and recommendation (follow/List-only/defer) to identity, rationale, scores, sample dates and original links. Keep per-pool coverage counts and deduplicate numeric IDs across pools.

Plan schema:

```json
{
  "version": 1,
  "account": {"id": "100", "handle": "reader_demo"},
  "created_at": "2026-10-27T17:00:00+00:00",
  "graph_sha256": "COPY_THE_GRAPH_HELPERS_CANONICAL_HASH",
  "actions": [
    {"target_id": "201", "handle": "operator_demo", "action": "unfollow", "reason": "Agent-written specific reason approved by the user", "before_following": true}
  ]
}
```

IDs are strings and handles lowercase without @. Maximum ten actions. Follow changes before_following=false to true; unfollow changes true to false. No duplicate IDs/handles or self-targets. Plan and snapshot must be recent (15 minutes for live apply). The preview emits the exact digest and account confirmation phrase. Any edit invalidates the old approval.

## Costs and receipts

Record each run's provider, run ID, query/relation, cap, result count, settled usageTotalUsd and remaining agreed session budget in session.md. Do not sum caps as actual spend, use a completion-time estimate as settled cost, or automatically reuse an approved budget next month.

The apply directory contains state.json, ledger.jsonl and a process lock. Preserve all three. Each intent is durable before its request; each result is confirmed, pending or unknown. A missing, truncated or mismatched receipt stops execution. Do not create a new directory to bypass it. Undo emits a new plan only; it cannot guarantee notifications or protected-account access are reversible.
