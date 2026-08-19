const token = process.env.RAILWAY_TOKEN;
async function gql(q,v){
  const r=await fetch('https://backboard.railway.app/graphql/v2',{
    method:'POST',
    headers:{'Content-Type':'application/json','Project-Access-Token':token},
    body:JSON.stringify({query:q,variables:v}),
    signal:AbortSignal.timeout(30000)
  });
  return(await r.json()).data;
}
(async()=>{
  const d=await gql(
    'query($sid:String!,$eid:String!){deployments(serviceId:$sid,environmentId:$eid,first:5){edges{node{id status createdAt}}}}',
    {sid:'0c2591fc-c1a8-421f-bc23-1f5aaa22ef5f',eid:'ac76694e-2c1c-4955-964a-471035cb4ca4'}
  );
  console.log(JSON.stringify(d,null,2));
})();
