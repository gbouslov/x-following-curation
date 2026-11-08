<bookmarking>
Use X Bookmarks first. Basic bookmarking is private and sufficient for this workflow. For every keeper, save the original post URL, author, date, the user's question and one sentence on what changes. Avoid copying entire threads into shared documents; links plus short paraphrases usually suffice. [X Bookmark help](https://help.x.com/en/using-x/bookmarks).
</bookmarking>

<decision_brief>
The user can paste up to five saved posts or provide an explicitly approved local export. Read each post and its original context when accessible. Never pretend a link was read if login or retrieval blocks it. Use this prompt:

“Read these saved posts against my question: [question]. Give me up to three useful findings, the original link and date for each, what each changes, what is only the author's assertion, and one next experiment. Do not create tasks, contact anyone or change my account.”

Make the judgments yourself. Do not run a text template or keyword scorer to choose the findings. Drop unsupported predictions, duplicate takes and promotional teasers from the brief. A result claimed by the author remains a claim until independently checked.
</decision_brief>

<optional_collection>
A personal knowledge collection can be a CSV or Markdown file on the user's machine. Start with fields `url, author, posted_at, saved_at, question, implication, next_check`. Private bookmarks, contact notes and relationship data stay private.

For an existing corpus pipeline, map those fields into the user's existing import contract; do not assume another person's folders or tooling exist. Use the official API and the user's own OAuth consent for private bookmarks; approve any API spend first. Public-post research services do not grant access to private bookmarks. Test one explicitly approved public example locally, verify the source link and deduplication, then prepare a larger import. Ask before uploading or sharing anything. This kit installs no pipeline or scheduled job.
</optional_collection>
