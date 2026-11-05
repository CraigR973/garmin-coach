# Batch 372 — Home and the check-in

5 Nov 2026. Decision 476. Base `f617dda`. **Unmerged; Craig's wording sign-off is required.**

## Acceptance

- **One immediate ride pick:** the open pick leads non-medical reminders, even before Read it. Its workout row does not repeat Approve & upload / Ignore. Existing length guidance is preserved, the planned-ride default is explicit, and a chosen variant uses the existing approval endpoint. Completed/skipped rows no longer offer a stale pick. Other actions keep their visibility rule.
- **Fewer asks:** symptoms precede feel; the advice answer is compactly above the note; secondary feel text and quick flags are optional. REM is asked on the first morning after actual issue (`windowStart`, including a midweek/Sunday issue), not daily. The assignment still covers its nights for objective observation collection; unanswered adherence is unknown, never inferred. Efficacy evidence will accumulate more slowly.
- **Done after the ride:** Home replaces the stale instruction after all planned rides are complete; a second unfinished ride prevents it. The stored morning/brief, colour and reason stay. A medical call retains its warning and appends completion.
- **No plan with logged activity:** no-plan state precedes the logged-activity branch; its existing builder link remains.
- **Reference copy:** friendly dates on Coach memory and handover; confirmed memory addresses its owner without changing stored facts or source quotes; handover headings use plain words with figures unchanged; experiments are explicitly ideas under test.

## Evidence

Focused backend: 27 passed, including first-morning REM eligibility for midweek and Sunday issues, preservation of stored legacy responses, and the draft wording pin. Frontend regressions cover unread pick visibility and order, duplicate-control absence, completed/unfinished rides, medical-call retention, no-plan plus logged activity, optional check-in controls and owner-subject memory display. Every new app phrase and the handover headings are pinned to `docs/drafts/2026-11-05-batch-372-wording.md`.

Browser: local Chromium, synthetic fixtures only, at 390 × 844 and 1280 × 800. Home's pick appears before Read it; choosing Tempo uses the existing `?variant=tempo` endpoint exactly once and the pick clears; check-in has symptoms first, visible note and expandable optional flags; Coach memory, Experiments and Handover render; five screens have no document-width overflow. Screenshots were visually inspected. This is not affected-iPhone acceptance or a production mutation test.

One focused check-in test timed out during parallel local load; rerun alone, all 23 passed. Earlier assertion/fixture failures were corrected (new wording, optional control targeting, and the first-morning-only REM response). No unrelated behaviour assertions were removed.

Morning and notes-reader modules are byte-identical to the base. No prompt bump, paid call, migration, deletion, auth or hosting change. No multi-row read of a JSONB-heavy model was introduced or changed. React review: derived display state stays in render, hooks remain unconditional, existing mutation ownership and accessible controls are retained.

## Release gate

Full local gate passes: **3,424 backend, 0 skipped**, on a reset Postgres at migration 044; Ruff/format/mypy pass; `pnpm -r test` shared 60/web 680 pass; web build passes; lint 0 errors, 9 existing warnings. Require both push and PR CI waves on the final head before merge. Local full-run results are recorded in STATUS and the PR; CI is linked from the PR checks.

Craig must sign off the wording before merge. After approval, the automatic close-out still requires the 06:00–11:00 London hold, exact-SHA Railway and Vercel health, readiness/jobs/auth/web checks and read-only container smoke. Batch 371 has not started.
