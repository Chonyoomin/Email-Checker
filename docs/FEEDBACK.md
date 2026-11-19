# Local opt-in feedback

After a real assessment, use **Report a malicious email** when you know the message
is malicious. Check the consent box to save its extracted text, headers and links
on this computer, then choose **Submit malicious example**. The UI matches the
assessed message before submitting. Failed/test-double assessments cannot submit.

A submission is a suggested scam label in the unverified feedback queue. It requires
verification before a later supervised training run; saving it does not change the
model immediately or add it to the frozen Phase7 dataset.

Use **Load saved examples** under Submitted examples to recover records after a
refresh or an uncertain save. It loads only labels, dates, identifiers and retention
metadata, never email content. Use **Load more examples** for additional pages and
**Delete saved example** to remove a record. If a save is not confirmed, check this
list before submitting again.

`POST /api/feedback` accepts JSON with an existing `scan_id`, `label`
(`scam`, `legitimate`, `unknown`), optional `reviewed` (default false), optional
`retain_content` (default false), and optional canonical `evidence` from preview.
Requests require the usual same-origin/local request protection and are capped at
1,500,000 bytes. Unknown fields and invalid combinations return a generic 422.

Providing evidence does not authorize retaining it: only `retain_content: true`
saves content, and that flag requires evidence. Retained evidence excludes account
scope, Gmail message ID and fingerprint; it can include sender, subject, body,
links and other extracted fields. Keep this local database and any exports private.

Unverified feedback and owner-declared reviewed examples use separate SQLite
tables. `reviewed: true` requires a known label and means the owner has reviewed
it; the application does not verify that judgment. Unknown labels remain
unverified. Feedback never changes predictions, calibrates or trains a model.

`GET /api/feedback/export` requires `X-Email-Checker-Request: 1`, including browser
requests. It returns `records` and `next_after`. Request at most 25 records per
page (`limit`, default 10); pass the returned cursor as `after` until it is null.
Each record identifies whether it is reviewed and includes evidence only if it
was retained. Stop submitting feedback during a multi-page export for a stable
listing. No export files are written automatically. Add `include_content=false`
for metadata-only listing: the query excludes the email-content column and returns
`content_retained` rather than `evidence`. The default `include_content=true` keeps
the existing content export behavior. All query names must be recognized and unique.

`DELETE /api/feedback/{feedback_id}` uses the normal local mutation protections.
It removes either kind of record, with SQLite secure deletion enabled for that
operation. Deletion covers the app's active database, not separately saved exports,
filesystem snapshots or backups. Scan metadata contains no retained email content
and remains separate. A missing record returns 404.
