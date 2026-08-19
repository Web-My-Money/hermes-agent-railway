// Set hermes startCommand to /entrypoint.sh with wmm-credentials install prepended.
// This is needed because Railway's auto-deploy webhook isn't wired to the fork,
// so we can't rebuild the Docker image. Instead, we prepend the install to the
// startCommand which runs before the baked-in entrypoint.
const token = process.env.RAILWAY_TOKEN;
if (!token) { console.error('RAILWAY_TOKEN not set'); process.exit(2); }

const HERMES_SERVICE_ID = '0c2591fc-c1a8-421f-bc23-1f5aaa22ef5f';
const ENV_ID = 'ac76694e-2c1c-4955-964a-471035cb4ca4';

// This startCommand does:
// 1. Installs telegram deps via uv pip (was in the old override)
// 2. Clones and installs wmm-credentials (non-fatal)
// 3. Registers wmm-credentials-gateway in config.yaml (non-fatal)
// 4. Fixes hardcoded tokens in MCP config (non-fatal)
// 5. Execs /entrypoint.sh (the baked-in entrypoint handles git-cred, auto-update, hermes start)
const startCommand = `bash -c '
set -e

# Telegram deps (was in old Railway override)
/root/.local/bin/uv pip install --python /opt/hermes-agent/venv/bin/python "python-telegram-bot[webhooks]==22.8" "aiohttp==3.14.3" 2>/dev/null || true

# wmm-credentials install (non-fatal)
if [ -n "$GH_TOKEN" ]; then
  rm -rf /tmp/wmm-credentials
  git clone --depth 1 -b master "https://x-access-token:$GH_TOKEN@github.com/Web-My-Money/wmm-credentials.git" /tmp/wmm-credentials 2>/dev/null && cd /tmp/wmm-credentials && npm install --omit=dev --ignore-scripts 2>/dev/null && echo "wmm-credentials: installed" || echo "WARN: wmm-credentials install failed (non-fatal)"
fi

# Register wmm-credentials-gateway MCP in config.yaml
if [ -f /tmp/wmm-credentials/scripts/wmm-local-mcp.mjs ]; then
  node -e "
    const fs=require(\\\"fs\\\");
    const p=\\\"/root/.hermes/config.yaml\\\";
    let c=\\\"\\\"; try{c=fs.readFileSync(p,\\\"utf8\\\")}catch{}
    if(c.includes(\\\"wmm-credentials-gateway\\\")){console.log(\\\"wmm-credentials-gateway: already registered\\\");process.exit(0)}
    const entry=\\\"\\\\n  wmm-credentials-gateway:\\\\n    command: node\\\\n    args:\\\\n      - /tmp/wmm-credentials/scripts/wmm-local-mcp.mjs\\\\n    env:\\\\n      WMM_MCP_CONNECT: \\\\\\\"true\\\\\\\"\\\\n\\\";
    if(c.includes(\\\"mcp_servers:\\\")){c=c.replace(/^(mcp_servers:)/m,\\\"\\$1\\\"+entry)}else{c+=\\\"\\\\nmcp_servers:\\\"+entry}
    fs.writeFileSync(p,c);console.log(\\\"wmm-credentials-gateway: registered\\\")
  " || echo "WARN: MCP registration failed (non-fatal)"
fi

exec /entrypoint.sh
'`;

async function gql(q, v) {
  const r = await fetch('https://backboard.railway.app/graphql/v2', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Project-Access-Token': token },
    body: JSON.stringify({ query: q, variables: v }),
    signal: AbortSignal.timeout(45000),
  });
  const json = await r.json();
  if (json.errors) { console.error('GQL_ERRORS', JSON.stringify(json.errors, null, 2)); process.exit(1); }
  return json.data;
}

(async () => {
  await gql(
    'mutation($sid: String!, $eid: String!, $input: ServiceInstanceUpdateInput!) { serviceInstanceUpdate(serviceId: $sid, environmentId: $eid, input: $input) }',
    { sid: HERMES_SERVICE_ID, eid: ENV_ID, input: { startCommand } }
  );
  console.log('hermes startCommand updated (wmm-credentials + /entrypoint.sh)');

  const check = await gql(
    'query($sid: String!, $eid: String!) { serviceInstance(serviceId: $sid, environmentId: $eid) { startCommand } }',
    { sid: HERMES_SERVICE_ID, eid: ENV_ID }
  );
  if (!check.serviceInstance.startCommand.includes('wmm-credentials')) {
    console.error('READ-BACK MISMATCH'); process.exit(1);
  }
  console.log('Read-back OK');

  await gql(
    'mutation($sid: String!, $eid: String!) { serviceInstanceRedeploy(serviceId: $sid, environmentId: $eid) }',
    { sid: HERMES_SERVICE_ID, eid: ENV_ID }
  );
  console.log('hermes REDEPLOYED with wmm-credentials integration');
})();
