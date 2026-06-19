# Status

> The cross-tool handoff doc. **Read the "Now" block at the start of a session;
> update it (and prepend to the Log) at the end.** See `AGENTS.md` for the
> handoff protocol, `DECISIONS.md` for why, `ARCHITECTURE.md` for the spec.

## Now

**Phase:** 0 — repo scaffold.

**Done:** repo seeded from WC2026 infra; project docs written (`ARCHITECTURE.md`,
`AGENTS.md` + `CLAUDE.md` symlink, `DECISIONS.md`, this file); WC-specific docs,
runbooks, agent-commands and Claude command-wrappers pruned to a clean baseline.

**Next (Phase 0 remaining)** — ready-to-run kickoff prompts (model + thinking per stage) are in **`docs/phase-0-session-prompts.md`**:
1. **Strip the football domain** — backend models/routers/services/migrations,
   frontend pages/components, `packages/shared` scoring; rename `@wc2026/shared`;
   update package.json names, CI workflow, README. Goal: a building skeleton with
   auth + an empty dashboard, no football references.
2. **Provision hosting** (needs Craig's accounts): new Supabase project, Railway
   service, Vercel project, GitHub repo + remote.
3. **Deployable skeleton** live.

**Then (Phase 1):** the data model from real JSON shapes (`~/garmin-spike/out/`),
the three sync jobs, the 84-night backfill, the morning/post-workout analysis.

## Gotchas
- Python is **3.12** (`~/.local/bin/python3.12`); system `python3` is 3.7 and breaks installs. No api venv yet.
- Repo has **no GitHub remote yet** and is **not deployed**.
- The football domain is **still present** — don't model new tables on it; use `ARCHITECTURE.md` §5 + the spike JSON.

## Log
- **2026-06-19** — Phase 0 started: seeded repo, wrote project docs, set up cross-tool structure (AGENTS.md canonical, CLAUDE.md symlink, DECISIONS + STATUS), pruned WC cruft. Data sources (Garmin/Hive/weather) already validated via spikes; analysis-engine output validated with a real sample.
