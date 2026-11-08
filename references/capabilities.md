# Retrieval, access and cost

Checked 27 October 2026 through official X documentation, Apify actor pages and unauthenticated public actor metadata. No paid actor run, live OAuth login or X relationship write was made in this build. Documentation establishes the supported interface; a user's first approved pilot establishes whether it works for their account today.

## The practical routes

| Need | Recommended route | Limits and coverage |
| --- | --- | --- |
| Current public following/followers | API Dojo user actor | Two separate jobs; cap and verify counts. A succeeded run is not proof of a full graph |
| Exact graph before a write | X user-context API | Complete pagination plus intended-account verification; incomplete snapshots cannot authorize writes |
| Recent posts/topic discovery | API Dojo tweet actor | Query and item capped; search is a sample, never an entire timeline |
| A public List's members | X List-members endpoint, or reviewed xquik graph export | Separate from List timeline posts; not a built-in List-fetch command |
| No credentials | User-supplied export or manual Lists | Import is supported, completeness remains unverified until reconciled |

## X API v2

The current model is prepaid pay-per-use, with Enterprise separately available. Do not assume historical Free/Basic/Pro plan permissions. Following/follower resources cost $0.010 each at standard rates; qualifying owned reads cost $0.001 each. The discount requires the app owner and authenticated user to match the endpoint user. Posts cost $0.005 each. Generic user-interaction creates cost $0.015/request and interaction deletes $0.010/request; confirm the applicable follow/unfollow rate in the user's console. Every verification lookup also consumes resources. [Official pricing](https://docs.x.com/x-api/getting-started/pricing).

| Purpose | Endpoint | Published limit |
| --- | --- | --- |
| Following | GET /2/users/{id}/following | 300 requests/15 minutes per app and user |
| Followers | GET /2/users/{id}/followers | 300 requests/15 minutes per app and user |
| Follow | POST /2/users/{id}/following | 50 requests/15 minutes per user |
| Unfollow | DELETE /2/users/{id}/following/{target_id} | 50 requests/15 minutes per user |

Graph pages accept up to 1,000 results and a pagination token. Continue until next_token is absent. IDs are numeric strings. Use OAuth user authorization with follows.read for graph access and follows.write for changes, plus tweet.read/users.read. App-only tokens cannot perform these writes. Account entitlement, restrictions and response headers can impose tighter limits. The kit uses much smaller ten-action batches and a 60-second minimum between attempts; those are local choices, not official safe allowances. [Following](https://docs.x.com/x-api/users/get-following), [followers](https://docs.x.com/x-api/users/get-followers), [follow](https://docs.x.com/x-api/users/follow-user), [unfollow](https://docs.x.com/x-api/users/unfollow-user), [limits](https://docs.x.com/x-api/fundamentals/rate-limits), [authentication mapping](https://docs.x.com/fundamentals/authentication/guides/v2-authentication-mapping).

Lists use GET /2/lists/{id}/members with the required entitlement. Recheck the [List-members reference](https://docs.x.com/x-api/lists/get-list-members) before a new adapter. Never promise that a scraper can see protected, blocked or deleted data.

## Apify actors

Public metadata API returns pricingInfos. Select the latest effective startedAt, inspect every charge event and use the user's plan tier; an old table or a primary-item price alone is insufficient.

| Actor | Confirmed documented input/capability | Listed events |
| --- | --- | --- |
| [apidojo/twitter-user-scraper](https://apify.com/apidojo/twitter-user-scraper) | twitterHandles, getFollowing/getFollowers, maxItems | $0.0004/item + $0.016/relation query + $0.004/profile query; conservative budget ignores free first-page discounts |
| [xquik/x-follower-scraper](https://apify.com/xquik/x-follower-scraper) | twitterHandles, relation=following/followers/list_members, maxItems | $0.00015/item all listed tiers; platform usage is separately paid by user |
| [apidojo/tweet-scraper](https://apify.com/apidojo/tweet-scraper) | searchTerms, sort, maxItems | $0.0004/post all listed tiers |
| [xquik/x-tweet-scraper](https://apify.com/xquik/x-tweet-scraper) | Alternative post search; not the bundled default | $0.00015/post all listed tiers; platform usage separately paid by user |

The bundled tools implement the two API Dojo routes; xquik is a documented alternative, not a silent fallback. API Dojo's graph page documents a five-object minimum and limits free users to five runs/month with ten items/run. Large exports require suitable account access. The graph actor's published two-relation example advertises first-page discounts; the kit budgets conservatively instead. Actor documentation and pricing can change; the scripts recheck metadata before execution and refuse unfamiliar pricing structures.

Every paid start includes Apify's server-side maxTotalChargeUsd as well as maxItems. Each output has a run receipt. A timeout or lost response is not permission to start a second paid run; recover the first run ID. Dataset pages are bounded; graph IDs are deduplicated during normalization, while the agent deduplicates search posts/authors before assessment. Verify settled usageTotalUsd at least 15 seconds after completion and keep per-run and aggregate session totals. A cap may truncate results; report that gap. [Actor metadata API](https://docs.apify.com/api/v2/act-get), [start/run options](https://docs.apify.com/api/v2/act-runs-post), [run details](https://docs.apify.com/api/v2/actor-run-get), [dataset items](https://docs.apify.com/api/v2/dataset-items-get).

## Policy and failure behavior

Review [X automation rules](https://help.x.com/en/rules-and-policies/x-automation) and [account behavior rules](https://help.x.com/en/rules-and-policies/x-rules-and-best-practices). The tools support personally reviewed curation, not indiscriminate growth automation. Stop on restrictions, 401/403/429, missing coverage, pending requests or ambiguous outcomes. Never retry an uncertain mutation. Slow requests do not override account rules.
