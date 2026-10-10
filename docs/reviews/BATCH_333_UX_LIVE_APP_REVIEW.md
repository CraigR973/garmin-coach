# Batch 333 — UX and the live app (audit wave #5, R7)

**Date:** 9–10 Oct 2026
**Pass:** R7 of the 327–333 wave (`docs/reviews/BATCH_327-333_AUDIT_SCOPE.md`)
**Lens:** product designer — every surface Mark touches, every state, one morning as one story,
every Mark-facing line since 1 Sep, accessibility and speed, Mark's own words about the app.
**Mode:** read-only. Nothing written to production; no device token minted; no paid call ($0).
**Base:** `42a6a98` (production). Wave #4 base: `2178381` (`BATCH_241_UX_LIVE_APP_REVIEW.md`).
**Companion:** `BATCH_333_MARK_SCORECARD.md` (plain words, for Craig to read as Mark).

*(in progress — written section by section)*

## Method

**A live render was achieved, on the production bundle.** Wave #4 rendered the Vite dev server;
this pass built the shipped front end (`vite build` of `apps/web` at `42a6a98`, Node 24.21, into
the gitignored scratch folder, never into the repo) and served the minified bundle, so bundle
sizes and load shape are the real artefact's. Headless Chromium (Playwright 1.60, the repo's own
install) drove it at **390 × 844**, `isMobile`, `hasTouch`, `en-GB`, `Europe/London`, in a
**fresh browser context per route and per state**, light and dark.

**The API was a local read-only mock** (`scratchpad/wave5/r7/mock_server.py`): it serves GETs from
fixture files and **returns 405 on every non-GET**; the browser driver also refuses every non-GET
and every request to any other host, and logs them. No auth endpoint is called (the bundle reads
its token from local storage; the driver seeds a dummy string there), so **no device token was
minted or read**.

**The fixtures are production responses, not reconstructions.** `dump_fixtures.py` ran the
shipped FastAPI app in-process under `railway run` with two dependency overrides (the current user
is Mark's profile; every request's session sits on a connection with
`default_transaction_read_only = on`, plus `SET TRANSACTION READ ONLY`, rolled back), every
outbound credential blanked and every non-database host refused at DNS. It saved the real
`{data, meta, errors}` envelopes for 39 GET routes (daily loop for 7, 8, 9, 10, 12 and 19 Oct;
coach thread; plan builder; schedule; week ahead; sleep; trends; reviews; experiments; holiday;
handover). A write probe on the same connection was refused, and one GET route that writes
(`/notifications/preferences`, which inserts a default row) failed on the read-only connection
and was not captured. Because the app parses its main payloads through the shipped `@coach/shared`
Zod schemas, a fixture that did not match the contract would have rendered an error card: none
did.

**States** (generating, failed, rest day, holiday, no plan, Zwift rail states, schema drift,
offline, server error) were produced by transforming those real envelopes in the driver, one
field at a time, from the shapes the API code produces. Each is labelled where it appears.

**Labels.** `observed` = seen rendered in this session (or in production data). `proved` = the
shipped code driven with crafted inputs (a transformed envelope through the real bundle).
`implemented` = read in the code. `computed` = derived from production data by a script.

**Where the evidence is.** `scratchpad/wave5/r7/out/` (per-render JSON audit, page text and a
full-page screenshot), gitignored. Nothing from it is committed.

## 1. Summary

## 2. What optimal looks like

## 3. Findings

## 4. Follow-through

## 5. G8 and parked rows re-verified

## 6. For reconsideration

## 7. Hypotheses

## 8. Limitations

## 9. Probe log
