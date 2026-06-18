// Quick CourtListener connectivity test
// Run: node test-cl.mjs

const TOKEN = '7fe67802ac4d98d2be84a07590179c8feb6d418f';
const BASE = 'https://www.courtlistener.com/api/rest/v4';

async function main() {
  console.log('Testing CourtListener citation lookup...');
  const res = await fetch(`${BASE}/citation-lookup/`, {
    method: 'POST',
    headers: { Authorization: `Token ${TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: '424 U.S. 319' }),
  });
  console.log('Status:', res.status);
  const body = await res.json();
  console.log('Response:', JSON.stringify(body, null, 2));

  const hit = body?.[0];
  if (hit?.clusters?.[0]?.id) {
    const clusterId = hit.clusters[0].id;
    console.log('\nFetching cluster', clusterId, '...');
    const cr = await fetch(`${BASE}/clusters/${clusterId}/`, {
      headers: { Authorization: `Token ${TOKEN}` },
    });
    const cluster = await cr.json();
    console.log('Case name:', cluster.case_name);
    console.log('Sub-opinions:', cluster.sub_opinions?.slice(0, 2));
  }
}

main().catch(console.error);
