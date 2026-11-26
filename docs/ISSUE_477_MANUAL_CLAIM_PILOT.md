# Issue #477 — manual claim fallback pilot (NOT ENABLED)

This is an isolated proposal, not a replacement for the current editor instructions.
Primary investigation: synchronous Git Data commit/CAS from a normal ChatGPT chat
was tested on branch `test/issue-477-sync-reserve`, with an isolated fixture only.
Direct GitHub reads and writes work; the remaining blocker is full canonical Python
pre-validation in the same chat. Never substitute informal JS checks for that gate.

The fallback retains the existing source of truth: `data/site_news_pool.json`
on main, `editorial_routing.json`, and the existing Python `next_item` function.
No new claim status, separate reservation registry, or change to reader semantics.

After approval and deployment only:
- For an explicit manual editor command, create exactly one unique file
  `data/editorial_claims/requests/manual-<operation-id>.json`, with
  `{"schema_version":1,"action":"claim_next","worker":"hpii-manual-editor"}`.
- Never overwrite a request. If the write response is lost, read the same path.
- Read the same-name receipt in `data/editorial_claims/receipts/`.
  Poll only within a bounded current chat turn when the available tool supports it.
  Do not create a second operation merely because the first receipt is pending.
- For `reserved`, verify the receipt and reread main's pool record; require
  matching ID, sequence, status in_review, and review_started_at. Only then
  continue. If pending, failed, or changed, do not draft from an unconfirmed claim.
  Old receipts are historical records, not proof of current reservation ownership.
- Existing autonomous and short workers retain their protocols. Checkpoint,
  return and approve continue using existing state transitions, not new receipts.
- The action validates the entire snapshot before and after selection, commits pool
  and receipt together, retries from fresh main after any non-fast-forward conflict.
  The request itself is asynchronous; this is not proof of a synchronous one-turn
  UX. The real request/receipt latency and same-turn continuation must be tested
  before any editor instructions are changed.

No actual news reserved during this pilot. No deployment or publication.
