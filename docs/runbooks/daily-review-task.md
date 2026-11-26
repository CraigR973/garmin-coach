# The daily review's scheduled task (Batch 391, Decision #513)

The daily reviewer runs on Craig's Claude Pro plan as a Claude Code scheduled task. Every
day at 21:30 London it follows `docs/agent-commands/loop-review.md`: it reads the day
through the app's private feed, checks it, and files findings in the queue. It is in
**shadow mode** for two weeks and changes nothing. Craig sees its findings in the Sunday
digest (`weekly-ops-digest`, 19:00 London).

Craig's choices (25 Nov): 21:30 London, Sonnet 5.5, one shared token, and he tells Mark
himself.

## Setting it up (Craig's steps)

Never paste the token into a chat, a commit or a PR.

**A. Make the token.** In Terminal on the Mac:

```bash
openssl rand -hex 32
```

Copy the 64 characters it prints.

**B. Railway.** On the `api` service, open **Variables** and add two variables with the
**same** value:

- `OPS_FEED_READ_TOKEN`
- `OPS_FEED_WRITE_TOKEN`

Press **Deploy** if Railway shows the changes as waiting. The feed then answers 401 to
anyone without the token, where it answered 404 before.

**C. The scheduled task.** At claude.ai, under **Code**, open **Scheduled tasks** and create
a new one:

1. **Repository:** `CraigR973/garmin-coach`, on `main`.
2. **Environment:** create a new environment named `garmin-coach-review`:
   - **Network access:** **Limited**. Keep **Allow package managers** ticked.
   - **Allowed domains:** `api-production-e2bc7.up.railway.app`
   - **Network secrets → Add:**
     - **Secret type:** Bearer
     - **Allowed websites:** `api-production-e2bc7.up.railway.app`
     - **Header name:** `Authorization`
     - **Prefix:** `Bearer`
     - **Value:** the token from A
   - **Environment variables:** none.
3. **Connectors:** remove any that are listed. The task needs none.
4. **Prompt:** `Follow docs/agent-commands/loop-review.md exactly. Shadow mode: change nothing.`
5. **Model:** **Sonnet 5.5**, chosen in the prompt box's model selector.
6. **Schedule:** custom, with the cron `CRON_TZ=Europe/London 30 21 * * *`.
7. Save it.

**D. Tell Mark,** in your own words. For example: "An AI helper now checks the coach's
answers and reads each evening for mistakes. It can't change anything on its own, and I
see everything it finds."

Then tell the session running 391. It starts the first run straight away and checks it:
the run's log, the items it filed, that it touched nothing else, and that the repo's
Supabase MCP server did not connect.

## Changing it later

- **New token:** change both Railway variables and the network secret's value together.
- **Pause the reviewer:** disable the scheduled task. Nothing in the app depends on it.
