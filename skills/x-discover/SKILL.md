---
name: x-discover
description: Finds and assesses new X creators through goal-based searches, keeper conversations and public Lists. Use after goals or an audit reveals missing topics or viewpoints.
---

<objective>
Find people whose posts improve the user's decisions, including useful small accounts. Return a short, explained selection rather than a giant popular-account directory.
</objective>
<quick_start>
Read local/goals.md, local/following.json, local/classification.csv when present, `references/capabilities.md` and `references/session-files.md`. The starter directory is a seed, never the answer. Read every retrieved post before recommending its author.
</quick_start>
<process>
1. Name the three most valuable gaps in the current feed. For each write a public query using the user's decision question, a practitioner term and an appropriate date. Start with three queries of 30–50 posts each; agree a maximum candidate pool (default 100 unique authors), shortlist (default 12), and total spend. No source text containing client/private identifiers goes into a query.
2. Preview a query with `python3 scripts/apify_fetch.py search --query 'enterprise AI implementation since:YYYY-MM-DD -filter:retweets' --max-items 50 --max-cost-usd 0.05 --output local/discovery-q1.json`. Use a real date. Add --execute only after budget approval. Run sequentially, improving the next query from what the prior one missed. Search recent original work; a minimum-likes filter can help broad searches but must not exclude the small-expert route.
3. Expand through substantive replies/quotes and people the strongest keepers cite. Inspect the actual conversation before treating an interaction as endorsement. Use public List members from X GET /2/lists/{id}/members with approved access, or the documented xquik graph actor relation=list_members through a separately reviewed capped adapter/export. The bundled search helper retrieves posts, not List members; never substitute a List's timeline for its membership. Keep query, conversation and List sources distinct.
4. Deduplicate by numeric author ID across all pools and remove current follows, prior rejected/churned targets and unavailable identities. Inspect five to ten recent original posts per finalist. Score the same four 0–3 dimensions as x-classify. Write local/discovery.csv yourself: identity, pool, goal gap, score breakdown, two original post links/dates, why worth reading, caveat and follow/List-only/defer recommendation. Vendor ties and secondhand reports deserve scrutiny, not automatic rejection.
5. Show at most 12 recommended additions and a short deferred list, grouped by the user's questions. Include a counterview and a low-volume specialist if supported. Account count is a cap, never a quota. Record retrieved posts, unique authors, reviewed finalists, duplication and settled spend; never claim every search author was fully assessed. Send the user's selected additions to x-apply as a fresh exact plan.
</process>
<success_criteria>
Each recommendation fills a named gap and has original, recent examples. All pools and caps are accounted for, already-followed people are excluded, and the shortlist is human-chosen by the agent. No follow occurs during discovery.
</success_criteria>
