# X following curation

A meta-skill that curates your X / Twitter feed around what you want to learn, with Claude Code or Codex.
Your agent interviews you about your goals, reads what every account you follow actually posts, and finds people worth adding.
Then it makes the follows and unfollows for you through the X API, in small paced batches, with a receipt for every change so any of them can be reversed.

## Five-minute quickstart

1. Clone this repo and open its folder in Claude Code or Codex. Python 3.10+ on macOS or Linux is the only tool dependency; no Python packages to install.
   ```bash
   git clone https://github.com/gbouslov/x-following-curation.git
   cd x-following-curation
   ```
2. Paste this prompt. No keys or paid calls are needed to start:
   > Read AGENTS.md and run x-setup, then x-goals. I want a useful feed for [your work]. Ask the five questions if needed. Use only files I explicitly give you. Show the plan and cost before any paid retrieval, and the exact changes before touching my account.
3. Try the offline demonstration:
   ```bash
   python3 scripts/demo.py
   python3 -m unittest discover -s tests -q
   ```

The first session produces your goals, a keep/review/unfollow table, a creator shortlist and an exact change preview. Budget about 60 minutes once you have an account and API access. A new X developer app can take longer to set up. Start with [manual setup](references/setup.md) if you are new to X; you can use private Lists without following everyone.

## What your agent does

| Job | Skill | You get |
| --- | --- | --- |
| Secure your account and connect your own tools | [x-setup](skills/x-setup/SKILL.md) | A working setup and a chosen retrieval budget |
| Understand what you want to learn | [x-goals](skills/x-goals/SKILL.md) | Goals from your notes, chats or five questions |
| Export your following and followers | [x-pull-graph](skills/x-pull-graph/SKILL.md) | Separate, dated snapshots with coverage counts |
| Review everyone you follow | [x-classify](skills/x-classify/SKILL.md) | Keep, review or unfollow, with post examples and reasons |
| Find useful new voices | [x-discover](skills/x-discover/SKILL.md) | A capped shortlist from topic searches, conversations and Lists |
| Follow and unfollow for you | [x-apply](skills/x-apply/SKILL.md) | The changes made through the X API in small batches, with receipts and an undo plan |
| Read, save and revisit | [x-read-daily](skills/x-read-daily/SKILL.md), [x-recurate](skills/x-recurate/SKILL.md) | A 15-minute routine and monthly refresh |

The agent makes the judgments. Python fetches, checks, previews and logs. Claude and Codex follow identical [operating rules](AGENTS.md); no plugin or private infrastructure is required. Open the skill files directly when your runtime does not automatically discover `skills/`.

## Cost to run

Documentation and public actor pricing checked **27 October 2026**. Your AI subscription or model usage is separate.

| Retrieval | Cost for 1,000 results | Conditions |
| --- | --- | --- |
| Apify graph, API Dojo | At most about **$0.42** in listed actor events for one account and one relation | $0.40 items + $0.016 query + $0.004 profile, before any applicable platform fees |
| Apify post search, API Dojo | **$0.40** in listed actor events | Each returned post; spend cap also set server-side |
| X following/followers | **$10 standard; $1 qualifying owned reads** | Owned discount requires your own app and matching authenticated app owner |

A starter Apify pull of 1,000 following, 1,000 followers and 500 posts budgets about **$1.04** in listed actor events. Each relation has its own cap; repeat pulls cost again. Use a smaller pilot first. X writes and account/target verification reads add charges; the tools never buy credits. Check your account's actual rates and limits before approval. See [current capabilities, limits and sources](references/capabilities.md).

## Your keys and your data

Set `APIFY_TOKEN` and/or `X_USER_ACCESS_TOKEN` privately in your terminal environment. Do not paste them into chat. The bundled tools read environment variables, never browser sessions or another person's credential stores. For X writes, use your own app's OAuth user token with `tweet.read users.read follows.read follows.write`. [Authentication and commands](references/api-and-safety.md) include the optional PKCE login helper.

Keep your working files in ignored `local/` and receipts in a private state directory outside Git. Preview commands make no network requests. Paid reads require `--execute`; writes additionally require the exact preview digest and account confirmation, after your explicit approval. Undo prepares another plan for approval; refollowing a private account may require that person's acceptance.

## See the real process

[A complete fictional session](examples/session/README.md) shows the files your agent creates. The [starter directory](references/accounts.md) is an example for one reader profile (AI services and deals), dated 27 October 2026; your goals decide who belongs in your feed.

MIT licensed. Nothing in setup publishes your work or sends a message.
