---
name: x-classify
description: Reviews every followed account against the user's goals and recent authored posts. Use to build keep, review and unfollow decisions before changing a feed.
---

<objective>
Make the user's daily feed more useful without mistaking fame, silence, a badge or a keyword for quality. Judge each account in context; preserve meaningful relationships and useful counterviews.
</objective>
<quick_start>
Read local/goals.md, local/following.json, `references/session-files.md`, `references/reading-and-curation.md` and the worked example in `examples/session/README.md`. Use `scripts/apify_fetch.py search` for approved, capped recent-post retrieval; read actual text and original URLs yourself.
</quick_start>
<process>
1. Record the input graph hash and number of unique following IDs. Keep one output row per ID. For each account inspect its public identity and ideally five to ten original posts over the last 60 to 90 days; retain post IDs, dates and links in local/posts.json. Sparse accounts may require an older sample. Deduplicate retweets and distinguish authored commentary from somebody else's quoted content.
2. Work within the agreed aggregate spend. Search with from:HANDLE and an actual since: date; do not require likes for low-volume experts. If retrieval is missing, inaccessible or truncated, use review and name the gap. A bio alone cannot support an unfollow. If budget cannot cover all posts, retain review rows for the unassessed accounts and report the remaining count.
3. Write judgments yourself. Score 0–3 each for decision relevance, firsthand specificity, useful-to-promotional ratio and contribution beyond existing voices (total 0–12). Explain the numbers with post examples, never follower count. A high score normally suggests keep; a clearly off-goal account with a representative sample can suggest unfollow. No mechanical threshold overrides a pinned contact, expert, relationship uncertainty or deliberate counterview.
4. Create local/classification.csv using the schema in session-files: keep/review/unfollow, specific reason, sample size/date range, post URLs, scores and exception flag. Explain why the user would miss or not miss it. Distinguish high-volume noise from a useful seller the user studies. Do not infer personal warmth from a follow. Read every row against the approved goals.
5. Verify output unique IDs equal input unique IDs, no unknown/duplicate IDs, totals sum, and every proposed unfollow has sampled post support with no exception. List incomplete rows as review. Show totals and the full proposed removals to the user; an audit is a recommendation, not approval to act. Proceed to discovery, then x-apply only for explicitly selected rows.
</process>
<success_criteria>
Every available followed ID has exactly one disposition. Keepers and removals have specific goal-based rationale and original examples; uncertainty stays review. The user can inspect all proposed removals, and no script has chosen what they should do.
</success_criteria>
