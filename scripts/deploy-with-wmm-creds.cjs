// Set hermes startCommand to /entrypoint.sh.
// All wmm-credentials + Infisical CLI setup lives in entrypoint.sh (auto-deployed from GitHub).
const token = process.env.RAILWAY_TOKEN;
if (!token) { console.error('RAILWAY_TOKEN not set'); process.exit(2); }

const HERMES_SERVICE_ID = '0c2591fc-c1a8-421f-bc23-1f5aaa22ef5f';
const ENV_ID = 'ac76694e-2c1c-4955-964a-471035cb4ca4';

const startCommand = '/entrypoint.sh';

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
  console.log('hermes startCommand reset to /entrypoint.sh');

  const check = await gql(
    'query($sid: String!, $eid: String!) { serviceInstance(serviceId: $sid, environmentId: $eid) { startCommand } }',
    { sid: HERMES_SERVICE_ID, eid: ENV_ID }
  );
  if (check.serviceInstance.startCommand !== '/entrypoint.sh') {
    console.error('READ-BACK MISMATCH: startCommand is', check.serviceInstance.startCommand);
    process.exit(1);
  }
  console.log('Read-back OK');

  await gql(
    'mutation($sid: String!, $eid: String!) { serviceInstanceRedeploy(serviceId: $sid, environmentId: $eid) }',
    { sid: HERMES_SERVICE_ID, eid: ENV_ID }
  );
  console.log('hermes REDEPLOYED');
})();
