# Upstream sync guide

This repo is a WMM fork of the **dormant** wrapper template
`mazshakibaii/hermes-agent-railway`. The wrapper itself is rarely updated.
The real upstream we care about is the Hermes agent:
`https://github.com/NousResearch/hermes-agent`.

## What we customize in this fork

- `entrypoint.sh` — git credential helper, runtime pip deps, wmm-credentials MCP
- `auth_proxy.py` — secret redaction, protected profiles, WebSocket fixes
- `Dockerfile` — pins `NousResearch/hermes-agent` to a release tag via `HERMES_REF`

## Updating the Hermes agent version

1. Check upstream releases: https://github.com/NousResearch/hermes-agent/releases
2. Update `HERMES_REF` in `Dockerfile`.
3. Build and test in a non-production environment.
4. Redeploy the Railway `hermes` service.

## Updating the wrapper template (rare)

```bash
git remote add upstream https://github.com/mazshakibaii/hermes-agent-railway.git
git remote set-url --push upstream DISABLE
git fetch upstream
git merge upstream/main
# Preserve the WMM customizations listed above.
git push origin main
```

After any merge, verify the git-credential bootstrap block at the top of
`entrypoint.sh` survived.
