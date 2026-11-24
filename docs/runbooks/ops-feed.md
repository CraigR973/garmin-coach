# The loop's private feed (Batch 390, Decision #512)

The daily reviewer (Batch 391) reads Mark's recent conversations, reads, ratings and
check-ins, and files findings, through four routes on the API. Two secrets gate them,
and with either unset its routes answer 404, so the feed is off until Craig sets them
when 391 starts. Nothing older than 14 days is ever returned (Craig's choice, 24 Nov).

| Route | Token | Returns |
|---|---|---|
| `GET /api/v1/ops/review-feed?since=&cursor=&limit=` | read | Chat turns, reads, ratings, check-ins, unhealthy jobs and queue items, oldest first, at most 300 a page, with a cursor |
| `GET /api/v1/ops/packets/{analysis_id}` | read | The stored packet a read was written from (inside the window) |
| `GET /api/v1/ops/items?state=open\|all` | read | Queue items, newest first |
| `POST /api/v1/ops/items` | write | Files a finding (`source` `review` or `suggestion`) |
| `PATCH /api/v1/ops/items/{id}` | write | Moves an item's state, sets its lane, attaches a proposal |

Every call sends `Authorization: Bearer <token>`. A wrong token, a missing one, or the
other route's token answers 401.

## Setting the tokens (with Batch 391)

1. Make two different secrets in Terminal, one at a time:

   ```bash
   openssl rand -hex 32
   ```

2. In Railway, on the `api` service, add `OPS_FEED_READ_TOKEN` and
   `OPS_FEED_WRITE_TOKEN`.
3. Give the same two values to the scheduled task as network secrets (391.2), never as
   plain environment variables.

Never paste them into a chat, a commit or a PR. To rotate one, change it in both places
together.

## What the queue keeps

`improvement_items` holds one row per finding. Repeats with the same fingerprint fold
into the open row (`occurrences`). `summary` and `detail` carry codes and dates only;
`words` (Mark's words, the coach's summary) is the only free text, and the daily
`improvement-items-retention` job (03:55 UTC) wipes it 90 days after a row closes
(Craig's choice). States move by `services/improvement_items.TRANSITIONS`; a closed
row (`verified`, `undone`, `dismissed`) never reopens, and the next occurrence opens a
new row.
