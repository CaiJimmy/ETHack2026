export default { async fetch(request, env) {
  const url = new URL(request.url);
  if (!url.pathname.startsWith('/api/')) return env.ASSETS.fetch(request);
  const origin = request.headers.get('Origin');
  if (origin && origin !== url.origin) return Response.json({error:'Origin not allowed'},{status:403});
  if (!['GET','POST','OPTIONS'].includes(request.method)) return new Response(null,{status:405});
  const target = new URL(url.pathname + url.search, 'https://climate-evidence-api.jimmycai.workers.dev');
  const headers = new Headers();
  if (request.headers.has('Content-Type')) headers.set('Content-Type',request.headers.get('Content-Type'));
  try { return await fetch(target,{method:request.method,headers,body:request.method==='POST'?request.body:undefined,redirect:'error'}); }
  catch { return Response.json({error:'The data service is unavailable. Please try again.'},{status:503}); }
} };
