// Reset hermes start command back to /entrypoint.sh (from the Dockerfile)
// The Railway UI override bypasses our entrypoint, so this fix is needed.
const token = process.env.RAILWAY_TOKEN;
if (!token) { console.error('RAILWAY_TOKEN not set'); process.exit(2); }

const HERMES_SERVICE_ID = '0c2591fc-c1a8-421f-bc23-1f5aaa22ef5f';
const ENV_ID = 'ac76694e-2c1c-4955-964a-471035cb4ca4';
const startCommand = '/entrypoint.sh';

async function gql(query, variables) {
  const res = await fetch('https://backboard.railway.app/graphql/v2', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Project-Access-Token': token },
    body: JSON.stringify({ query, variables }),
    signal: AbortSignal.timeout(45000),
  });
  const json = await res.json();
  if (json.errors) { console.error('GQL_ERRORS', JSON.stringify(json.errors)); process.exit(1); }
  return json.data;
}

(async () => {
  await gql(
    'mutation($sid: String!, $eid: String!, $input: ServiceInstanceUpdateInput!) { serviceInstanceUpdate(serviceId: $sid, environmentId: $eid, input: $input) }',
    { sid: HERMES_SERVICE_ID, eid: ENV_ID, input: { startCommand } }
  );
  console.log('hermes startCommand reset to: /entrypoint.sh');

  // Read-back verify
  const check = await gql(
    'query($sid: String!, $eid: String!) { serviceInstance(serviceId: $sid, environmentId: $eid) { startCommand } }',
    { sid: HERMES_SERVICE_ID, eid: ENV_ID }
  );
  console.log('read-back startCommand:', check.serviceInstance.startCommand);

  if (check.serviceInstance.startCommand === startCommand) {
    console.log('Confirmed. Triggering redeploy...');
    await gql(
      'mutation($sid: String!, $eid: String!) { serviceInstanceRedeploy(serviceId: $sid, environmentId: $eid) }',
      { sid: HERMES_SERVICE_ID, eid: ENV_ID }
    );
    console.log('hermes REDEPLOYED with /entrypoint.sh');
  } else {
    console.error('READ-BACK MISMATCH — not redeploying');
    process.exit(1);
  }
})();
