import test from 'node:test';
import assert from 'node:assert/strict';
import { searchWeb } from './web-search.js';

test('search enables grounding and preserves source attribution', async () => {
    const result = await searchWeb({ GEMINI_API_KEY: 'test' }, 'Recent disclosure', async (url, init) => {
        assert.deepEqual(JSON.parse(init.body).tools, [{ google_search: {} }]);
        return Response.json({ candidates: [{ finishReason: 'STOP', content: { parts: [{ text: 'A reported change.' }] }, groundingMetadata: {
            groundingChunks: [{ web: { uri: 'https://example.com/report', title: 'Report' } }, { web: { uri: 'javascript:alert(1)' } }],
            groundingSupports: [{ segment: { text: 'A reported change.' }, groundingChunkIndices: [0] }],
        } }] });
    });
    assert.equal(result.sources.length, 1);
    assert.equal(result.supports[0].groundingChunkIndices[0], 0);
});
test('ungrounded or failed responses are not presented as verified web findings', async () => {
    await assert.rejects(searchWeb({ GEMINI_API_KEY: 'test' }, 'Question', async () => Response.json({ candidates: [{ finishReason: 'STOP', content: { parts: [{ text: 'Unsupported claim' }] } }] })));
    await assert.rejects(searchWeb({ GEMINI_API_KEY: 'test' }, 'Question', async () => new Response('', { status: 429 })));
});
