# Lighthouse baseline — 25 May 2026

Pre-implementation baseline for the premium polish round 2 work
(`docs/polish-batches.md` U1–U5). The Phase 4 verification block will
compare against these numbers.

## Run details

| Field | Value |
|---|---|
| Target | `https://wc2026-staging.vercel.app/login` (deployed staging, public) |
| Lighthouse version | 12.8.2 |
| Form factor | mobile (default emulation, throttled) |
| User agent | HeadlessChrome 148 |
| Fetched at | 2026-05-25T16:41:02Z |
| Final URL | `https://wc2026-staging.vercel.app/login` |
| Branch | `feat/premium-polish` @ `1cd067e` (docs-only commits since `main`) |

> Authenticated routes (Dashboard, Predictions, etc.) are **not measured**
> in this baseline because Lighthouse's headless run can't easily prime
> the localStorage-backed auth tokens. If Phase 4 needs an authenticated
> comparison, we'll add a Playwright-driven Lighthouse run via the
> `lighthouse-ci` workflow.

## Category scores

| Category | Score |
|---|---|
| **Performance** | **0.82** |
| Accessibility | 0.96 |
| Best Practices | 1.00 |
| SEO | 1.00 |
| PWA | n/a (deprecated in Lighthouse 12) |

## Performance metrics

| Metric | Value | Score | Notes |
|---|---|---|---|
| First Contentful Paint | 1.9 s | 0.88 | Acceptable; budget is < 1.8 s |
| **Largest Contentful Paint** | **2.5 s** | **0.89** | On the threshold (good = < 2.5 s); LCP element is the wordmark splash |
| **Total Blocking Time** | **540 ms** | **0.54** | The dominant performance drag — likely framer-motion + Sentry init |
| Cumulative Layout Shift | 0.02 | 1.00 | Excellent — no visible shift |
| Speed Index | 2.3 s | 0.98 | Excellent |
| Time to Interactive | 3.3 s | 0.94 | Good |
| Max Potential FID | 360 ms | 0.24 | Poor — biggest input delay potential from JS init |
| Server response time | 23 ms | 1.00 | Excellent — Vercel edge |

## Resource summary (login splash, cold load)

| Type | Count | Transfer |
|---|---|---|
| Document | 1 | 1.6 KB |
| Stylesheet | 2 | 9.8 KB |
| **Script** | **4** | **105.3 KB** |
| Font (Outfit + JetBrains Mono) | 6 | 64.0 KB |
| Image (icon-192 precache) | 1 | 133.3 KB |
| Other | 4 | 4.4 KB |
| **Total** | **18** | **318.4 KB** |

Top JS chunks fetched on `/login`:

| Chunk | Transfer |
|---|---|
| `react-vendor-…js` | 55.9 KB |
| `index-…js` (entry) | 33.2 KB |
| `query-…js` (TanStack Query) | 13.7 KB |
| `workbox-window…js` | 2.6 KB |

## Failed audits worth fixing in this round

Lighthouse surfaced three real polish issues that the design audit
didn't already cover. These are folded into the U-batches as noted.

### 🔴 Color contrast — accessibility 0.96 (1 audit failing, weight 7)

Three elements failing WCAG AA 4.5:1 minimum on `/login`:

1. **`text-text-muted` eyebrow text** (`#5A6478`) on `bg-surface` `#131720` → contrast 3.01 (10 px font-mono). Same token is used as **every page eyebrow** across the app — `FIXTURES`, `STANDINGS`, `ACCOUNT & DEVICE`, etc. **High-impact fix.** Lift the token to ~`#7B859B` to clear 4.5:1.
2. **Sign-in button text** (`#FFFFFF` on `#10B981`) → contrast 2.53. The primary CTA failing AA is a visible quality issue. Switch the on-primary text colour from white to the dark `text-text-inverse` (`#0B0E13`) — gives 12.0:1.
3. **Tagline-adjacent small mono text** (`#5A6478` on `bg` `#0B0E13`) → 3.24. Same root cause as (1).

→ **Add to U3** ("Dashboard rebalance + copy polish") as U3.11 — token-level fix in `apps/web/src/theme/tokens.ts` + `apps/web/src/index.css`. Validates with Lighthouse re-run in Phase 4.

### 🟡 Total Blocking Time — performance 540 ms (weight 30)

TBT is the single biggest performance drag. Likely sources:
- React + framer-motion hydration on the `/login` entry (framer-motion is in `react-vendor`; could be split off the entry)
- Sentry SDK init on every page (already lazy — verify)
- Workbox SW registration on first load

→ **Watch in Phase 4.** A meaningful TBT fix is its own ticket — too tangential to the polish theme. If U5's motion code adds another 100+ ms TBT, raise as a Phase 4 follow-up.

### 🟢 LCP element is the wordmark, 2.5 s on the threshold

LCP is rendering the `THE STEELE / SPREADSHEET SYSTEM` Brand splash —
which loads `JetBrains Mono` from Google Fonts before painting. Two
cheap wins:

- Self-host the woff2 files in `apps/web/public/fonts/` and `link rel=preload` the two weights actually used on the splash (600 + 700)
- The current `font-mono` definition includes ~6 weight files; the splash only needs two

→ **Add to U1** (logo + brand work — fonts are part of the brand layer) as U1.5. Token fix, ~30 min.

## Targets for Phase 4

| Metric | Baseline | Floor (must clear) | Target (aim for) |
|---|---|---|---|
| Performance | 0.82 | 0.82 (no regression) | 0.90 |
| Accessibility | 0.96 | 0.96 (no regression) | 1.00 (after contrast fixes) |
| Best Practices | 1.00 | 1.00 | 1.00 |
| SEO | 1.00 | 1.00 | 1.00 |
| LCP | 2.5 s | 2.7 s | 2.0 s |
| TBT | 540 ms | 600 ms | 400 ms |
| CLS | 0.02 | 0.05 | 0.02 |
| Total transfer (cold /login) | 318 KB | 380 KB | 320 KB |

## How to reproduce

```sh
PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH" \
  npx --yes lighthouse \
  https://wc2026-staging.vercel.app/login \
  --form-factor=mobile \
  --screenEmulation.mobile=true \
  --output=json \
  --output-path=/tmp/lh-staging-login.json \
  --quiet \
  --chrome-flags="--headless=new --no-sandbox --disable-gpu"
```

Raw JSON is in `/tmp/lh-staging-login.json` (not committed; ~390 KB).
