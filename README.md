# Hermes Agent on Railway

Deploy [Hermes Agent](https://hermes-agent.nousresearch.com/) to Railway with one click. Hermes is an open-source AI agent by Nous Research with tool use, memory, messaging platform integrations, and a web dashboard.

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/TEMPLATE_ID?referralCode=REFERRAL_CODE)

## Features

This template goes beyond a basic Hermes deploy:

- **Full dashboard access** — manage config, API keys, sessions, logs, analytics, cron jobs, and skills from your browser. No SSH or CLI needed.
- **Messaging gateway included** — Telegram, Discord, and Slack bots run alongside the dashboard. Configure platform tokens in the UI, hit restart, and your bot is live.
- **Gateway management widget** — a floating status indicator and restart button injected into the dashboard. See at a glance if the gateway is running, restart it after config changes without redeploying.
- **Cookie-based auth** — password-protected login page with session cookies. No repeated browser auth prompts like basic auth templates.
- **Auto-updates** — pulls the latest Hermes release on every container restart. Always up to date, no manual intervention. Disable with `AUTO_UPDATE=false` to pin a version.
- **Zero config to start** — deploy with just a password, then set up everything else (LLM provider, API keys, messaging platforms) from the dashboard UI.
- **Persistent storage** — attach a Railway volume to keep sessions, memories, config, and logs across redeploys.

## Setup

1. Click the **Deploy on Railway** button above
2. Set `DASHBOARD_PASSWORD` (required)
3. Deploy — log in at your Railway URL
4. Add your LLM provider key (e.g. OpenRouter) on the **API Keys** page
5. Optionally configure Telegram/Discord/Slack tokens and hit **Restart** on the gateway widget

## Environment Variables

| Variable | Description |
|---|---|
| `DASHBOARD_USER` | Login username (default: `admin`) |
| `DASHBOARD_PASSWORD` | Login password (**required** — deploy will fail without it) |
| `AUTO_UPDATE` | Pull latest Hermes on every restart (default: `true`, set to `false` to pin version) |

All other configuration is done through the dashboard after deploy.

## Persistent Storage

To keep your data across redeploys, attach a Railway volume:

1. Right-click the service in your Railway project
2. Select **Attach Volume**
3. Set mount path to `/root/.hermes`

This persists sessions, memories, API keys, config, logs, and cron jobs.

## Architecture

```
Internet -> Railway -> Auth Proxy (cookie login) -> Hermes Dashboard (port 9119)
                           |
                           +-> Messaging Gateway (Telegram/Discord/Slack)
                           +-> /api/health (unauthenticated, for Railway health checks)
                           +-> /api/gateway/restart (authenticated, restart bot)
                           +-> /api/gateway/status (authenticated, check bot status)
```

## Resources

- [Hermes Agent Documentation](https://hermes-agent.nousresearch.com/docs)
- [GitHub Repository](https://github.com/NousResearch/hermes-agent)
- [Web Dashboard Guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard)

## WMM fork

This is `Web-My-Money`'s fork of [`mazshakibaii/hermes-agent-railway`](https://github.com/mazshakibaii/hermes-agent-railway), forked 2026-08-09 to fix a bug the upstream template can't fix via Railway config alone: nothing in `entrypoint.sh` configured a git credential helper, so git operations issued from Hermes's terminal-tool sandbox failed with `fatal: could not read Username for 'https://github.com'` even though `GH_TOKEN` was set correctly on the Railway service.

**What changed vs. upstream**: `entrypoint.sh` now configures `credential.helper 'store --file=/root/.git-credentials'` and writes that file from `GH_TOKEN` unconditionally, before the `AUTO_UPDATE` git pull and before the dashboard/sandbox process starts accepting terminal-tool calls. It never prints the token; it only logs whether the bootstrap ran (`git-credential-bootstrap: configured` / `skipped`). See the `fix(entrypoint): bootstrap git credential helper from GH_TOKEN` commit on `main` for the full diff and rationale.

### Staying in sync with upstream

The `main` branch here is expected to drift intentionally (our fix lives only here). To pull upstream improvements without losing it:

```bash
git remote add upstream https://github.com/mazshakibaii/hermes-agent-railway.git   # once per clone
git remote set-url --push upstream DISABLE                                        # we only fetch from upstream, never push to it
git fetch upstream
git merge upstream/main   # resolve conflicts, keeping the WMM entrypoint.sh credential-bootstrap block
git push origin main
```

Re-check after merging that the git-credential bootstrap block at the top of `entrypoint.sh` (and this README section) survived the merge — upstream has no knowledge of it and a large upstream rewrite of `entrypoint.sh` could silently drop it.

### Fast edit-deploy loop on Railway

The `hermes` service on Railway (project `Cloud-Agents-Stack`) is configured to **build from source directly from this GitHub repo** via Railway's native GitHub build integration (not a manually-built/pushed Docker image). That means:

1. Edit a file in this repo (e.g. `entrypoint.sh`), commit, and `git push origin main`.
2. Railway detects the push and rebuilds/redeploys `hermes` automatically — no manual image build or Railway config change needed for ordinary code fixes.
3. Watch build/deploy logs (`railway logs --service hermes` or the Railway MCP `get_logs` tool) to confirm the new deploy is healthy before considering the fix live.

Only reach for a manual Docker image push if you need to bypass Railway's build entirely (e.g. testing a build environment Railway's builder can't reproduce) — for normal fixes, pushing to this repo is the whole deploy step.
