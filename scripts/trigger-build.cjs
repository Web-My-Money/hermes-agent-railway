// Trigger a new Railway deployment (image build from latest git commit)
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
  if (json.errors) { console.error('GQL_ERRORS', JSON.stringify(json.errors, null, 2)); process.exit(1); }
  return json.data;
}

(async () => {
  // serviceInstanceRedeploy triggers a fresh build from current source
  const result = await gql(
    'mutation($sid: String!, $eid: String!) { serviceInstanceRedeploy(serviceId: $sid, environmentId: $eid) }',
    { sid: HERMES_SERVICE_ID, eid: ENV_ID }
  );
  console.log('Triggered new deployment (fresh build from git)');
  console.log(JSON.stringify(result, null, 2));
})();
