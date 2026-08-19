// Reconnect the hermes service source to the GitHub repo
// This re-wires the deploy trigger webhook
const token = process.env.RAILWAY_TOKEN;
if (!token) { console.error('RAILWAY_TOKEN not set'); process.exit(2); }

const HERMES_SERVICE_ID = '0c2591fc-c1a8-421f-bc23-1f5aaa22ef5f';
const ENV_ID = 'ac76694e-2c1c-4955-964a-471035cb4ca4';

async function gql(q, v) {
  const r = await fetch('https://backboard.railway.app/graphql/v2', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Project-Access-Token': token },
    body: JSON.stringify({ query: q, variables: v }),
    signal: AbortSignal.timeout(45000),
  });
  const json = await r.json();
  if (json.errors) {
    console.error('GQL_ERRORS', JSON.stringify(json.errors, null, 2));
    return null;
  }
  return json.data;
}

(async () => {
  // First check current source
  const status = await gql(
    'query($sid: String!, $eid: String!) { serviceInstance(serviceId: $sid, environmentId: $eid) { source { repo } } }',
    { sid: HERMES_SERVICE_ID, eid: ENV_ID }
  );
  console.log('Current source:', JSON.stringify(status?.serviceInstance?.source));

  // Reconnect the source to trigger webhook re-registration
  const result = await gql(
    'mutation($sid: String!, $eid: String!, $input: ServiceInstanceUpdateInput!) { serviceInstanceUpdate(serviceId: $sid, environmentId: $eid, input: $input) }',
    {
      sid: HERMES_SERVICE_ID,
      eid: ENV_ID,
      input: {
        source: {
          repo: 'Web-My-Money/hermes-agent-railway'
        }
      }
    }
  );
  console.log('Reconnect result:', result ? 'success' : 'failed');

  // Verify
  const verify = await gql(
    'query($sid: String!, $eid: String!) { serviceInstance(serviceId: $sid, environmentId: $eid) { source { repo } } }',
    { sid: HERMES_SERVICE_ID, eid: ENV_ID }
  );
  console.log('Verified source:', JSON.stringify(verify?.serviceInstance?.source));
})();
