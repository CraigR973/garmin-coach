# World Cup 2026 Prediction League

A private, invite-only prediction league PWA for the 2026 FIFA World Cup. Up to 15 players, full tournament coverage (104 matches), automatic result fetching, live leaderboard, and push notifications.

## Stack

- **Frontend:** React 18 + Tailwind CSS + shadcn/ui + Vite (PWA)
- **Backend:** Python 3.12 + FastAPI
- **Database:** PostgreSQL via Supabase
- **Hosting:** Vercel (frontend) + Railway (backend)

## Monorepo Structure

```
apps/
  api/          FastAPI backend
  web/          React + Vite frontend (PWA)
packages/
  shared/       Shared Zod schemas, TS types, scoring logic
migrations/     Alembic database migrations
docs/
  adr/          Architecture Decision Records
  runbooks/     Operational runbooks
```

## Prerequisites

- Node.js ≥ 20.x
- pnpm ≥ 9.x (`npm i -g pnpm`)
- Python 3.12

## Getting Started

1. Copy env vars: `cp .env.example .env` and fill in values
2. Install Node dependencies: `pnpm install`
3. Set up Python venv: `cd apps/api && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
4. Run migrations: `alembic upgrade head`
5. Start dev servers:
   - Backend: `cd apps/api && uvicorn main:app --reload`
   - Frontend: `cd apps/web && pnpm dev`

## Environment Variables

See [.env.example](.env.example) for all required variables.

## License

MIT
