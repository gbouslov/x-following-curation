# One complete fictional session

Run `python3 scripts/demo.py` from repo root. It uses local fixtures and a simulated API, creates temporary private receipts, previews two exact actions, verifies the simulated results and prepares an undo preview. It never reads a real token, calls a network service or changes an X account.

## What the agent supplies

Read [history.txt](history.txt), then [goals.md](goals.md). The current user priorities supersede rejected assistant suggestions about trading and follower growth. All accounts below are invented; the numbers identify fixtures only.

| Account | Current state | Agent assessment | Next action |
| --- | --- | --- | --- |
| operator_demo (201) | Followed | Keep: concrete delivery lessons answer question 1 | None |
| noise_demo (202) | Followed | Unfollow: representative sample is unrelated trading commentary | Proposed unfollow |
| contact_demo (203) | Followed | Review: pinned personal contact, sparse public sample | None |
| diligence_demo (204) | Not followed | Discover: concrete acquisition-diligence examples answer question 2 | Proposed follow |

The agent would read actual posts before making these judgments in a real session. The demo fixtures carry invented post examples to demonstrate the format, not a claim about a public creator.

## What the tools prove

The graph contains three unique followed IDs. Classification covers all three, discovery proposes one new ID, and only two actions enter the plan. Preview shows all target IDs, handles, reasons, the graph hash and a digest bound to the complete plan. The simulated apply checks the account, re-fetches its graph, resolves targets, records intent/result and advances a fake clock between actions.

The resulting simulated graph still contains the keeper and pinned contact, replaces the noise account with the discovery, and has three follows. Undo prepares exactly the two inverse actions from confirmed receipts. Every mutation function receives an injected fake transport, and the demo rejects network access.

For your own session, use the commands in [API and safety](../../references/api-and-safety.md). Fictional approvals, IDs and timestamps are never permission for a live operation.
