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

## How a teammate gets access to G Dog

1. The teammate DMs the bot on Telegram. G Dog replies with an 8-character pairing code (valid 1 hour), and they send that code to Fran.
2. Fran approves it one of two ways. He can open the dashboard (`PUBLIC_URL`, the `DASHBOARD_PASSWORD` login), go to **Pairing**, and click approve. Or he can tell G Dog in his own chat: `run: hermes pairing approve telegram <CODE>`.
3. The teammate messages again, and they're in. No restart is needed. To remove access: `hermes pairing revoke telegram <user_id>`. `hermes pairing list` shows who is approved.

`wmm_config_patch.py` turns pairing on (`platforms.telegram.unauthorized_dm_behavior: pair`). Set it to `ignore` in the dashboard to close the door again, and the boot patch will leave that choice alone.

**Owner vs teammate (since 2026-09-26, fork patch `Web-My-Money/hermes-agent#7`).** Fran (`HERMES_OWNER_TELEGRAM_ID`, default `8635020128`) is the only Telegram admin (`platforms.telegram.allow_admin_from`). A paired teammate:

- can use only session commands (`/new /stop /retry /undo /status /compress /title /queue /steer /btw /usage /context`), not `/approve`, `/yolo`, `/approvals`, `/config`, `/model`, `/restart`, `/update`;
- runs with `approvals.non_admin_mode: manual`. When a teammate's request hits a dangerous command, the approval card goes to **Fran's DM** (`approvals.non_admin_approver_chat`) and says who asked; the teammate sees "needs the owner's approval". No answer in 5 minutes = denied. Fran's own session keeps `approvals.mode` (off);
- is blocked outright (`approvals.non_admin_deny`) from commands that mention pairing, the allowlist, `config.yaml`/`hermes config`, or the secret-bearing quarantine. Only Fran can approve a new teammate.

This is a guard rail, not a sandbox: a teammate's G Dog still has the same terminal, repos and vault reach, and a command the dangerous-pattern detector doesn't flag runs without asking. Approve only people you would trust with that. To turn the guard off: `hermes config set approvals.non_admin_mode off`.

**Secret-bearing backups** live in `/root/.hermes/backups/secret-bearing/` (chmod 700, README inside). The Hermes fork read-denies that path for the agent's file tools; the hourly context sync writes its pre-redaction memory backups there (`--backup-dir`).

## WMM boot additions (entrypoint.sh)

| What | Where | Knobs |
|---|---|---|
| Shared WMM facts and skills: `Web-My-Money/wmm-agents` mirrored read-only at boot and hourly | `/opt/wmm-agents`: `skills/` is added to `skills.external_dirs`, `context/INDEX.md` is referenced from `SOUL.md`, and `context/hermes/*.md` is merged into `memories/` by wmm-agents' `context-sync.mjs --pull` | `WMM_AGENTS_REF` (default `main`), `WMM_AGENTS_REFRESH_SECONDS` (default `3600`) |
| WMM-managed config keys, applied before Hermes starts. Each one only fills a gap, and a timestamped `config.yaml.bak-wmm-config-*` is written when anything changes | `wmm_config_patch.py` | `HERMES_WMM_FALLBACK_MODEL` (default `xai-oauth/grok-4.5`, used when the fallback chain only repeats the primary model) |

The Hermes version is `HERMES_AGENT_REF` in the `Dockerfile`: a commit on `Web-My-Money/hermes-agent` `main`, which is upstream's release plus the WMM patches. Bump it by PR, and merging deploys it.

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
# Trigger Railway rebuild
