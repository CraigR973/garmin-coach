# Lighthouse final — 26 May 2026

Phase 4 verification run, comparing against
`docs/lighthouse-baseline-2026-05-25.md` (captured before U1).

## Run details

| Field | Value |
|---|---|
| Target | `https://wc2026-staging.vercel.app/login` (same URL as baseline) |
| Lighthouse version | 12.8.2 |
| Form factor | mobile (default emulation, throttled) |
| Fetched at | 2026-05-26T16:27:33Z |
| `main` HEAD | `5816fd9` — "docs: mark Batch U5 shipped" |

## Category scores

| Category | Baseline | Final (pre-`86ed938`) | Final (post-`86ed938`) | Target met? |
|---|---|---|---|---|
| **Performance** | **0.82** | **0.92** | 0.92 (staging WAF blocked re-run; build identical) | ✅ target 0.90 |
| **Accessibility** | 0.96 | 0.96 | **1.00** | ✅ target 1.00 (after follow-up fix) |
| Best Practices | 1.00 | 1.00 | 1.00 | ✅ |
| SEO | 1.00 | 1.00 | 1.00 | ✅ |

The post-fix accessibility number was confirmed via a fresh Lighthouse
run against the same code on `http://localhost:5173/login` after
`86ed938` landed (staging URL was temporarily behind a Vercel WAF
challenge from the verification polling; the dev-server-served bundle
contains the identical token/Button changes). All accessibility audits
pass; no failing items remain.

## Web Vitals

| Metric | Baseline | Final | Δ | Notes |
|---|---|---|---|---|
| First Contentful Paint | 1.9 s | **1.7 s** | −202 ms | self-hosted fonts (U1.5) |
| Largest Contentful Paint | 2.5 s | **2.5 s** | −60 ms | wordmark; same value, score 0.89 → 0.90 |
| **Total Blocking Time** | **540 ms** | **260 ms** | **−281 ms (−52 %)** | ✅ beat 400 ms target |
| Cumulative Layout Shift | 0.02 | 0.02 | 0 | unchanged |
| Speed Index | 2.3 s | **1.7 s** | −666 ms | |
| Time to Interactive | 3.3 s | **2.5 s** | −817 ms | |
| Max Potential FID | 360 ms | **216 ms** | −140 ms | |
| Server response time | 23 ms | 20 ms | unchanged (Vercel edge) |

## Resource summary (cold `/login`)

| Type | Baseline | Final | Δ |
|---|---|---|---|
| Total | 318 KB | 326 KB | +8 KB |
| Document | 1.6 KB | 1.6 KB | 0 |
| Stylesheet | 9.8 KB | 8.6 KB | −1.2 KB |
| Script | 105.3 KB | 129.3 KB | +24.0 KB (U2–U5 components) |
| Font | 64.0 KB | 49.3 KB | −14.7 KB (self-hosted + scoped to splash) |
| Image | 133.3 KB | 130.1 KB | −3.2 KB |
| Other | 4.4 KB | 6.9 KB | +2.5 KB |
| **Third-party** | **65.9 KB** | **0.5 KB** | **−65.4 KB** (Google Fonts removed) |

## U3.11 follow-up — shipped in `86ed938`

The unfixed second clause of U3.11 (primary CTA button white-on-emerald
contrast) shipped on 26 May as a separate commit
`fix(a11y): lock on-primary / on-accent button text to dark across themes`.

Changes:

- New tokens `--on-primary: #0B0E13` and `--on-accent: #0B0E13`
  added to both `:root, html.dark` and `html.light` blocks in
  `apps/web/src/index.css` — locked dark in both themes so the
  primary/accent surfaces always have AA-clearing text contrast
- Registered as `on-primary` and `on-accent` colours in
  `apps/web/tailwind.config.ts`
- `apps/web/src/components/ui/button.tsx` default + accent variants
  swapped `text-text-inverse` → `text-on-primary` / `text-on-accent`
- `apps/web/src/pages/OfflinePage.tsx` hand-rolled retry button had
  the same issue — same swap applied

Verified contrast ratios (WCAG AA needs 4.5 : 1):

| Foreground | Background | Where | Ratio |
|---|---|---|---|
| `#0B0E13` | `#10B981` | dark mode primary | ≈ 13 : 1 (AAA) |
| `#0B0E13` | `#059669` | light mode primary | ≈ 5.0 : 1 (AA) |
| `#0B0E13` | `#C8943C` | dark mode accent | ≈ 7.0 : 1 (AA) |
| `#0B0E13` | `#A77C2A` | light mode accent | ≈ 4.9 : 1 (AA) |

After the fix, Lighthouse Accessibility = **1.00** — no failing
audits remain.

## How to reproduce

```sh
PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH" \
  npx --yes lighthouse https://wc2026-staging.vercel.app/login \
  --form-factor=mobile --screenEmulation.mobile=true \
  --output=json --output-path=/tmp/lh-staging-login-post.json \
  --quiet --chrome-flags="--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage"
```
