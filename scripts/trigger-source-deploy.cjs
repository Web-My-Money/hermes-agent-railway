// Force a deployment from the latest commit on main
const token = process.env.RAILWAY_TOKEN;
if (!token) { console.error('RAILWAY_TOKEN not set'); process.exit(2); }

const HERMES_SERVICE_ID = '0c2591fc-c1a8-421f-bc23-1f5aaa22ef5f';
const ENV_ID = 'ac76694e-2c1c-4955-964a-471035cb4ca4';

async function gql(q, v) {
  const r = await fetch('https://backboard.railway.app/graphql/v2', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Project-Access-Token': token },
    body: JSON.stringify({ query: q, variables: v }),
    signal: AbortSignal.timeout(60000),
  });
  const json = await r.json();
  if (json.errors) { console.error('GQL_ERRORS', JSON.stringify(json.errors, null, 2)); }
  return json.data;
}

(async () => {
  // Try deploymentCreate which builds from a specific commit/branch
  console.log('Attempting deploymentCreate from main branch...');
  const result = await gql(
    `mutation($input: DeploymentCreateInput!) {
      deploymentCreate(input: $input) { id status createdAt }
    }`,
    {
      input: {
        serviceId: HERMES_SERVICE_ID,
        environmentId: ENV_ID,
      }
    }
  );
  console.log('Result:', JSON.stringify(result, null, 2));
})();
