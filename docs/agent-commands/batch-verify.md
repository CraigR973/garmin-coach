---
description: Run the local verification gate before pushing a batch branch.
---

# /batch-verify

Use this after implementation and before `/phase-closeout`. It gives the agent
one obvious place to prove the branch is ready.

Examples:

```text
/batch-verify U43
/batch-verify 14
```

## Steps

1. Verify branch and status:

   ```bash
   git -C /Users/craigrobinson/wc_2026_predictor symbolic-ref --short HEAD
   git -C /Users/craigrobinson/wc_2026_predictor status --short
   ```

   Warn if the branch is `main`. Verification may still run, but close-out will
   require a feature branch.

2. Determine touched areas:

   ```bash
   git -C /Users/craigrobinson/wc_2026_predictor diff --name-only main...HEAD
   git -C /Users/craigrobinson/wc_2026_predictor diff --name-only
   ```

3. Frontend gate, when `apps/web` or `packages/shared` changed:

   ```bash
   PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH" pnpm --dir /Users/craigrobinson/wc_2026_predictor/apps/web lint
   PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH" pnpm --dir /Users/craigrobinson/wc_2026_predictor/apps/web typecheck
   PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH" pnpm --dir /Users/craigrobinson/wc_2026_predictor/apps/web build
   PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH" pnpm --dir /Users/craigrobinson/wc_2026_predictor/apps/web test
   ```

4. Backend gate, when `apps/api`, `migrations`, or backend-affecting shared code
   changed:

   ```bash
   PYTHONPATH=/Users/craigrobinson/wc_2026_predictor/apps/api /Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python -m ruff check /Users/craigrobinson/wc_2026_predictor/apps/api
   PYTHONPATH=/Users/craigrobinson/wc_2026_predictor/apps/api /Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python -m ruff format --check /Users/craigrobinson/wc_2026_predictor/apps/api
   PYTHONPATH=/Users/craigrobinson/wc_2026_predictor/apps/api /Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python -m mypy /Users/craigrobinson/wc_2026_predictor/apps/api/src
   PYTHONPATH=/Users/craigrobinson/wc_2026_predictor/apps/api /Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python -m pytest /Users/craigrobinson/wc_2026_predictor/apps/api/tests
   ```

5. Shared package gate, when `packages/shared` changed:

   ```bash
   PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH" pnpm --dir /Users/craigrobinson/wc_2026_predictor/packages/shared test
   ```

   If a script is missing, report it and continue with the relevant frontend or
   backend tests that consume the shared package.

6. Print a concise result:

   ```text
   Ready for /phase-closeout U43: yes
   Verified: lint, typecheck, build, tests
   ```

## Optional helper

Agents may use:

```bash
/Users/craigrobinson/wc_2026_predictor/scripts/agent/batch-verify.sh U43
```

The helper runs the common gates and exits non-zero on failure.
