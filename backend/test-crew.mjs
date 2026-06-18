// Crew chat endpoint smoke test
// Run: node test-crew.mjs
// Requires the backend to be running on port 3001.

const BASE = 'http://localhost:3001';

const PAYLOAD = {
  userMessage:
    'Our startup signed an IP assignment agreement with a contractor six months ago. The contractor is now claiming he retains rights to the core algorithm because the agreement only covered "deliverables" not "inventions." Do we have a strong position?',
  matterContext: '',
};

async function main() {
  console.log('Hitting /api/crew/chat...');
  console.log('Payload:', JSON.stringify(PAYLOAD, null, 2), '\n');

  const res = await fetch(`${BASE}/api/crew/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(PAYLOAD),
  });

  console.log('Status:', res.status);
  console.log('Content-Type:', res.headers.get('content-type'), '\n');

  if (!res.ok) {
    console.error('Error response:', await res.text());
    process.exit(1);
  }

  // The endpoint streams Server-Sent Events. Read and parse each event.
  const text = await res.text();
  const lines = text.split('\n').filter((l) => l.startsWith('data: '));

  let fullReply = '';
  let citations = [];

  for (const line of lines) {
    const raw = line.slice('data: '.length).trim();
    if (raw === '[DONE]') break;
    try {
      const event = JSON.parse(raw);
      if (event.type === 'content_delta') fullReply += event.text;
      if (event.type === 'citations') citations = event.citations ?? [];
      if (event.type === 'error') {
        console.error('Stream error:', event.error);
        process.exit(1);
      }
    } catch {
      // ignore malformed lines
    }
  }

  console.log('=== REPLY ===');
  console.log(fullReply);

  if (citations.length) {
    console.log('\n=== CITATIONS ===');
    for (const c of citations) {
      console.log(`- ${c.citation}`);
      if (c.url) console.log(`  ${c.url}`);
      if (c.relevance) console.log(`  ${c.relevance}`);
    }
  } else {
    console.log('\n(no citations returned)');
  }

  console.log('\nDone.');
}

main().catch(console.error);
