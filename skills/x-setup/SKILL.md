---
name: x-setup
description: Sets up a quiet X account and the user's own retrieval tools. Use on first run, for a new account, or when connecting Apify or X OAuth.
---

<objective>
Get the user to a useful first reading session, with a secure account and a clear choice of data access. No technical background or public posting is required.
</objective>
<quick_start>
From the repository root, read `references/setup.md`, `references/capabilities.md` and `references/api-and-safety.md`. Run `python3 scripts/demo.py` to see the offline workflow. Check Python 3.10+; no packages are required.
</quick_start>
<process>
1. Establish whether the user has an X account. If new, guide secure signup, authenticator/security-key 2FA and private recovery storage using the setup reference. Keep contact upload off unless they choose it. Never collect credentials or recovery codes.
2. Explain the working surface: Following or private Lists for daily reading, topic search for discovery. Lists let them read someone without following. Show one post relevant to their work; do not require posting or buying Premium.
3. Create ignored `local/` for this user's session. Read `AGENTS.md`. Run x-goals before collecting account data. Default source consent is none beyond the files explicitly supplied.
4. Recommend Apify for economical public graph and post collection; use X API for complete authenticated graph checks and approved relationship changes. Manual/export input is also supported. Read the live pricing sources, agree an aggregate dollar budget and per-run caps, then show a tiny pilot. No paid call until the user approves the cost. Do not buy credits or silently switch providers.
5. Ask them to set their own environment variables privately. Report only present/missing, never values. Apify needs APIFY_TOKEN; X user operations need X_USER_ACCESS_TOKEN and their verified account ID/handle. The optional PKCE helper uses X_CLIENT_ID for a public Native App. Use `python3 scripts/oauth_session.py --dry-run` first. OAuth login is not permission to change relationships. Proceed with x-goals, then x-pull-graph.
</process>
<success_criteria>
The user can open a quiet reading surface and identify a useful post. Source permission and retrieval budget are explicit, secrets stay private, and the agent can preview the workflow with no network. No account change or paid call is implied by setup.
</success_criteria>
