#!/usr/bin/env bash
set -e

# WMM: configure a git credential helper so git operations issued from
# Hermes's terminal-tool sandbox (and this script's own AUTO_UPDATE pull
# below) can authenticate against GitHub using GH_TOKEN. Without this,
# in-container git calls fail with "could not read Username for
# 'https://github.com'" because no credential source is ever configured.
# This does not print or log the token value.
git config --global credential.helper 'store --file=/root/.git-credentials'
if [ -n "$GH_TOKEN" ]; then
  printf 'https://x-access-token:%s@github.com\n' "$GH_TOKEN" > /root/.git-credentials
  chmod 600 /root/.git-credentials
  echo "git-credential-bootstrap: configured"

  # `gh` does not read .git-credentials, and the terminal tool scrubs GH_TOKEN
  # from its subprocess env: it is on Hermes's _HERMES_PROVIDER_ENV_BLOCKLIST
  # (tools/environments/local.py), and terminal.env_passthrough deliberately
  # refuses blocklisted names (GHSA-rhgp-j443-p4rf). So GH_TOKEN being set here
  # did nothing for the agent: `gh` was logged out, and G Dog answered
  # "You are not logged into any GitHub hosts" (seen 2026-09-25).
  #
  # Write gh's OWN store directly (/root/.config/gh/hosts.yml), the way gh
  # itself does when there is no keyring. NOT `gh auth login --with-token`:
  # that validator refuses this token -- "error validating token: missing
  # required scope 'read:org'" (boot log 2026-09-25). The service's GH_TOKEN is
  # an OAuth token scoped gist, repo, workflow (verified via X-OAuth-Scopes),
  # which covers everything the agent does with gh -- pr, api repos/..., repo
  # clone, workflow. read:org only gates org/team listing, and only the login
  # validator insists on it; gh does not re-check scopes when it reads hosts.yml.
  #
  # (#9 guessed at a network race. It was not: keeping the error instead of
  # sending it to /dev/null is what surfaced the real cause.)
  #
  # Exposes nothing new -- the same token is on disk one line up -- and it does
  # not weaken the blocklist, which still keeps the token out of subprocess env.
  # /root/.config is not on the volume, so this runs every boot.
  if command -v gh >/dev/null 2>&1; then
    GH_LOGIN=$(curl -fsS --max-time 15 --retry 3 -H "Authorization: token $GH_TOKEN" \
      https://api.github.com/user 2>/dev/null | sed -n 's/.*"login": *"\([^"]*\)".*/\1/p' | head -1)
    ( umask 077; mkdir -p /root/.config/gh
      printf 'github.com:\n    oauth_token: %s\n    user: %s\n    git_protocol: https\n' \
        "$GH_TOKEN" "${GH_LOGIN:-x-access-token}" > /root/.config/gh/hosts.yml )
    if GH_ERR=$(env -u GH_TOKEN -u GITHUB_TOKEN gh api user --jq .login 2>&1); then
      echo "gh-auth-bootstrap: configured (${GH_ERR})"
    else
      echo "WARN: gh-auth-bootstrap: hosts.yml written but gh cannot authenticate - the agent's gh will be logged out: $(printf '%s' "$GH_ERR" | head -c 300)"
    fi
  fi
else
  echo "git-credential-bootstrap: skipped (GH_TOKEN not set)"
fi

# ─── Runtime pip dependencies (previously in Railway startCommand override) ──
# These are needed for the Telegram webhook server and were previously installed
# via an inline startCommand that bypassed this entrypoint.
if command -v uv >/dev/null 2>&1; then
  VIRTUAL_ENV=/opt/hermes-agent/venv uv pip install \
    "python-telegram-bot[webhooks]==22.8" \
    "aiohttp==3.14.3" --quiet 2>/dev/null || echo "WARN: pip deps install failed (non-fatal)"
fi

AUTO_UPDATE="${AUTO_UPDATE:-true}"

if [ "$AUTO_UPDATE" = "true" ]; then
  echo "Checking for Hermes updates..."
  cd /opt/hermes-agent
  if git pull --recurse-submodules 2>&1 | grep -v 'Already up to date'; then
    echo "Updating dependencies..."
    VIRTUAL_ENV=/opt/hermes-agent/venv uv pip install -e ".[all]" --quiet
    echo "Update complete."
  else
    echo "Already up to date."
  fi
fi

# ─── wmm-credentials MCP (non-fatal) ───────────────────────────────────────
# Installs the WMM credentials package from GitHub so Hermes can call
# wmm_credentials_status / wmm_credentials_check / wmm_credentials_context
# through the local stdio MCP server. Uses GH_TOKEN for private repo clone.
WMM_CREDENTIALS_VERSION="${WMM_CREDENTIALS_VERSION:-master}"
if [ -n "${GH_TOKEN:-}" ]; then
  (
    set -e
    rm -rf /tmp/wmm-credentials
    git clone --depth 1 -b "$WMM_CREDENTIALS_VERSION" \
      "https://x-access-token:${GH_TOKEN}@github.com/Web-My-Money/wmm-credentials.git" \
      /tmp/wmm-credentials
    cd /tmp/wmm-credentials && npm install --omit=dev --ignore-scripts 2>/dev/null
  ) && echo "wmm-credentials: installed ($WMM_CREDENTIALS_VERSION)" \
    || echo "WARN: wmm-credentials install failed — continuing (non-fatal)"
else
  echo "WARN: GH_TOKEN not set — cannot install wmm-credentials"
fi

# ─── Infisical CLI (required by wmm-env for headless secret retrieval) ─────────
# wmm-credentials-gateway needs the Infisical CLI to actually fetch secrets from
# the WMM vault using INFISICAL_API_URL + INFISICAL_TOKEN. Install once per boot.
INFISICAL_VERSION="0.43.120"
if ! command -v infisical >/dev/null 2>&1 || [ "$(infisical --version 2>/dev/null | tr -d '[:space:]')" != "$INFISICAL_VERSION" ]; then
  echo "Installing Infisical CLI ${INFISICAL_VERSION} via npm..."
  (
    set -e
    npm install -g "@infisical/cli@${INFISICAL_VERSION}" >/tmp/infisical-install.log 2>&1
  ) && echo "infisical-cli: installed ${INFISICAL_VERSION}" \
    || { echo "WARN: infisical-cli install failed (non-fatal)"; cat /tmp/infisical-install.log; }
else
  echo "infisical-cli: already installed ${INFISICAL_VERSION}"
fi

# ─── wmm-env on PATH, and a loud vault preflight ───────────────────────────────
# Two gaps this closes.
#   1. The clone above installs the package but never puts its bin on PATH, so an
#      agent had to know the literal `node /tmp/wmm-credentials/bin/wmm-env.mjs`.
#      It never did — it reached for `wmm-env` and got "command not found".
#   2. A vault that authenticates but reads nothing is this stack's known silent
#      failure (wmm-credentials docs/AUTO_SYNC_ROLLOUT_2026-08-26.md): Infisical
#      prints "Injecting 0 Infisical secrets", exits 0, and the caller believes it
#      succeeded. Counting at boot turns that into a visible WARN.
if [ -f /tmp/wmm-credentials/bin/wmm-env.mjs ]; then
  chmod +x /tmp/wmm-credentials/bin/wmm-env.mjs
  ln -sf /tmp/wmm-credentials/bin/wmm-env.mjs /usr/local/bin/wmm-env
  echo "wmm-env: linked to /usr/local/bin/wmm-env"
else
  echo "WARN: wmm-env missing — agents cannot inject vault secrets"
fi

if [ -z "${INFISICAL_TOKEN:-}${INFISICAL_MACHINE_IDENTITY_CLIENT_ID:-}" ]; then
  echo "WARN: vault-preflight: no INFISICAL_TOKEN and no machine identity set - every wmm-env run will fail"
elif command -v infisical >/dev/null 2>&1; then
  VAULT_N="$(infisical export --projectId "${INFISICAL_PROJECT_SLUG:-wmm-hub}" --env "${INFISICAL_ENV:-dev}" --path /shared --format=dotenv 2>/dev/null | grep -cE '^[A-Za-z_][A-Za-z0-9_]*=' || true)"
  if [ "${VAULT_N:-0}" -gt 0 ]; then
    echo "vault-preflight: OK - ${VAULT_N} secrets readable at ${INFISICAL_ENV:-dev}:/shared"
  else
    echo "WARN: vault-preflight: authenticated but read 0 secrets at ${INFISICAL_ENV:-dev}:/shared - token scope is wrong"
  fi
fi

# Register wmm-credentials-gateway in Hermes MCP config (config.yaml on volume).
# Hermes reads mcp_servers from /root/.hermes/config.yaml directly.
if [ -f /tmp/wmm-credentials/scripts/wmm-local-mcp.mjs ]; then
  node - <<'WMMEOF' || echo "WARN: wmm-credentials MCP registration in config.yaml failed (non-fatal)"
const fs = require("fs");
const configPath = "/root/.hermes/config.yaml";
let config = "";
try { config = fs.readFileSync(configPath, "utf8"); } catch {}

// Check if already registered
if (config.includes("wmm-credentials-gateway")) {
  console.log("wmm-credentials-gateway: already in config.yaml");
  process.exit(0);
}

// Append MCP server entry to config.yaml
// Hermes config.yaml uses a flat mcp_servers: block
const entry = `
  wmm-credentials-gateway:
    command: node
    args:
      - /tmp/wmm-credentials/scripts/wmm-local-mcp.mjs
    env:
      WMM_MCP_CONNECT: "true"
`;

if (config.includes("mcp_servers:")) {
  // Insert after the mcp_servers: line
  config = config.replace(/^(mcp_servers:)/m, `$1${entry}`);
} else {
  // Add a new mcp_servers block
  config += `\nmcp_servers:${entry}\n`;
}
fs.writeFileSync(configPath, config);
console.log("wmm-credentials-gateway: registered in config.yaml");
WMMEOF
fi

# ─── Fix MCP env vars to reference Railway service vars ─────────────────────
# Ensure config.yaml MCP server env entries use ${VAR} substitution from Railway
# service variables instead of hardcoded token values.
node - <<'FIXEOF' || echo "WARN: MCP env var fix failed (non-fatal)"
const fs = require("fs");
const configPath = "/root/.hermes/config.yaml";
let config = "";
try { config = fs.readFileSync(configPath, "utf8"); } catch { process.exit(0); }

let changed = false;

// Replace hardcoded GitHub PAT in MCP config with env var reference
// Pattern: GITHUB_PERSONAL_ACCESS_TOKEN followed by a literal ghp_/gho_ value
const ghRe = /(GITHUB_PERSONAL_ACCESS_TOKEN:\s*)(["']?)(?:ghp_|gho_)[a-zA-Z0-9_]+\2/g;
if (ghRe.test(config)) {
  config = config.replace(ghRe, "$1${GH_TOKEN}");
  changed = true;
}

// Replace hardcoded Supabase token with env var reference
const sbRe = /(SUPABASE_ACCESS_TOKEN:\s*)(["']?)sbp_[a-f0-9]+\2/g;
if (sbRe.test(config)) {
  config = config.replace(sbRe, "$1${SUPABASE_ACCESS_TOKEN}");
  changed = true;
}

if (changed) {
  fs.writeFileSync(configPath, config);
  console.log("mcp-env-fix: replaced hardcoded tokens with env var references");
} else {
  console.log("mcp-env-fix: no hardcoded tokens found (already clean or using ${} refs)");
}
FIXEOF

# ─── Shared WMM context + skills (Web-My-Money/wmm-agents) ───────────────────
# Desktop Hermes, G Dog and the Multica agents read the same curated facts and
# skills from one private repo instead of each machine learning the same traps on
# its own. This mirrors it read-only into /opt/wmm-agents at boot and hourly:
#   skills/               -> skills.external_dirs (wmm_config_patch.py below)
#   context/INDEX.md      -> pointed at from SOUL.md (block appended below)
#   context/hermes/*.md   -> merged into /root/.hermes/memories by wmm-agents'
#                            own `context-sync.mjs --pull`. It backs up first and
#                            never exceeds this install's memory limits.
# Every piece tolerates a missing folder, so a repo that hasn't shipped context/
# yet is picked up on the next refresh. A failed refresh keeps the last good copy.
# Auth is the git credential helper configured at the top of this file.
WMM_AGENTS_DIR="${WMM_AGENTS_DIR:-/opt/wmm-agents}"
WMM_AGENTS_REF="${WMM_AGENTS_REF:-main}"
WMM_HERMES_HOME="${HERMES_HOME:-/root/.hermes}"
wmm_agents_refresh() {
  if [ -d "$WMM_AGENTS_DIR/.git" ]; then
    git -C "$WMM_AGENTS_DIR" fetch --quiet --depth 1 origin "$WMM_AGENTS_REF" \
      && git -C "$WMM_AGENTS_DIR" reset --quiet --hard FETCH_HEAD
  else
    rm -rf "$WMM_AGENTS_DIR" \
      && git clone --quiet --depth 1 --branch "$WMM_AGENTS_REF" \
        https://github.com/Web-My-Money/wmm-agents.git "$WMM_AGENTS_DIR"
  fi || { echo "WARN: wmm-agents: refresh failed - keeping the previous copy, if any"; return 1; }
  echo "wmm-agents: $(git -C "$WMM_AGENTS_DIR" log -1 --format='%h %cs') skills=$(find "$WMM_AGENTS_DIR/skills" -name SKILL.md 2>/dev/null | wc -l) context=$([ -f "$WMM_AGENTS_DIR/context/INDEX.md" ] && echo yes || echo not-yet)"
  if [ -f "$WMM_AGENTS_DIR/scripts/context-sync.mjs" ] && [ -d "$WMM_AGENTS_DIR/context/hermes" ]; then
    # Summary lines only: an "omitted" line quotes the start of a local memory entry.
    node "$WMM_AGENTS_DIR/scripts/context-sync.mjs" --pull \
      --hermes-dir "$WMM_HERMES_HOME/memories" --config "$WMM_HERMES_HOME/config.yaml" 2>&1 \
      | grep -v 'omitted (still in backup)' | sed 's/^/wmm-agents: memory: /'
  fi
}
wmm_agents_refresh || true

SOUL_FILE="$WMM_HERMES_HOME/SOUL.md"
if [ -f "$SOUL_FILE" ] && ! grep -q 'wmm-shared-context' "$SOUL_FILE"; then
  cat >> "$SOUL_FILE" <<'SOULEOF'

<!-- wmm-shared-context: appended once by hermes-agent-railway/entrypoint.sh -->
## Shared WMM facts
Curated, secret-scanned facts that every WMM agent shares (Claude Code, Hermes desktop, Multica) live
in `/opt/wmm-agents/context/`, refreshed hourly from `Web-My-Money/wmm-agents`. Read
`context/INDEX.md` before exploring a topic, then open only the `context/facts/<slug>.md` you need.
Shared skills load from `/opt/wmm-agents/skills`. To add or correct a fact, open a PR on wmm-agents
(never push to main).
SOULEOF
  echo "wmm-agents: pointer appended to SOUL.md"
fi

# WMM-managed config keys (shared skills dir, Telegram pairing, a fallback that is
# not the primary again). Runs now because Hermes rewrites config.yaml itself once
# it is up; see wmm_config_patch.py for each rule.
python /wmm_config_patch.py || echo "WARN: wmm-config: patch failed (non-fatal)"

# Hourly refresh. A plain loop rather than a Hermes cron job: it needs no model,
# and must keep working when the model gateway is down.
( while sleep "${WMM_AGENTS_REFRESH_SECONDS:-3600}"; do wmm_agents_refresh || true; done ) &

hermes dashboard --host 127.0.0.1 --port 9119 --no-open &

exec python /auth_proxy.py
