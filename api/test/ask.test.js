import { test } from 'node:test';
import assert from 'node:assert/strict';
import { answerQuestion, readQuestion } from '../src/ask.js';
import worker from '../src/index.js';
const env = { GEMINI_API_KEY: 'test-only' };
const model = (...outputs) => async (url, options) => {
    assert.ok(url.startsWith('https://generativelanguage.googleapis.com/'));
    assert.equal(options.headers['x-goog-api-key'], 'test-only');
    const out = outputs.shift();
    if (out?.operation) {
        const names = { companies: 'list_companies', plumes: 'list_plumes', details: 'get_company_details', company_benchmarks: 'benchmark_companies', hotspots: 'find_persistent_hotspots', unsupported: 'explain_limit' };
        const args = out.operation === 'details' ? { tickers: out.tickers } : out.operation === 'unsupported' ? { message: out.message } : Object.fromEntries(out.filters.map(({ key, value }) => [key, /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : value]));
        return Response.json({ candidates: [{ finishReason: 'STOP', content: { parts: [{ functionCall: { id: 'call-1', name: names[out.operation], args } }] } }] });
    }
    return out instanceof Response ? out : Response.json({ candidates: [{ finishReason: 'STOP', content: { parts: [{ text: JSON.stringify(out) }] } }] });
};
const plan = { operation: 'plumes', filters: [{ key: 'gas', value: 'CH4' }, { key: 'region', value: 'Texas' }, { key: 'sort', value: 'rate' }], tickers: [], message: '' };
const data = { data: [{ plume_id: 'p1', gas: 'CH4', plume_longitude: 12, plume_latitude: 34, emission_auto: 100, emission_uncertainty_auto: 20, observed_at_utc: '2025-01-01T00:00:00Z' }], notes: ['Observation, not facility'], source: 'plume_observations', page: { next_offset: null } };
test('question routes to validated endpoint with source-built map points', async () => {
    const r = await answerQuestion('Largest methane observations in Texas', env, async path => {
        assert.equal(path, '/api/plumes?gas=CH4&region=Texas&sort=rate&limit=5');
        return Response.json(data);
    }, model(plan, { answer: 'Observed rate is 100 kg CH4/hour [p1].', evidence_ids: ['p1'] }));
    assert.equal(r.status, 'ok'); assert.equal(r.visualization.points[0].longitude, 12);
    assert.equal(r.evidence[0].data.emission_auto, 100);
});
test('Gemini function call can select a deterministic benchmark API', async () => {
    const benchmarkPlan = { operation: 'company_benchmarks', filters: [{ key: 'metric', value: 'gap' }, { key: 'ticker', value: 'XOM' }], tickers: [], message: '' };
    const row = { ticker: 'XOM', company_name: 'Exxon Mobil', gics_sector: 'Energy', gap_pct_yr: 3, sector_average: 1.2, sector_percentile: 90, sector_peer_count: 20, benchmark_metric: 'gap' };
    const result = await answerQuestion('How does XOM compare with its sector?', env, async path => {
        assert.equal(path, '/api/insights/company-benchmarks?metric=gap&ticker=XOM&limit=5');
        return Response.json({ data: [row], notes: ['Same-sector benchmark'], source: 'benchmark', page: { next_offset: null } });
    }, model(benchmarkPlan, { answer: 'XOM is at the 90th percentile among its peers [XOM].', evidence_ids: ['XOM'] }));
    assert.equal(result.status, 'ok'); assert.equal(result.visualization.type, 'company_table');
    assert.equal(result.evidence[0].data.sector_peer_count, 20);
});
test('Gemini can combine multiple validated APIs into a decision brief', async () => {
    let turn = 0;
    const fetcher = async () => {
        turn++;
        if (turn === 1) return Response.json({ candidates: [{ finishReason: 'STOP', content: { parts: [
            { functionCall: { id: 'call-1', name: 'list_companies', args: { sector: 'Utilities', sort: 'gap', limit: 2 } } },
            { functionCall: { id: 'call-2', name: 'benchmark_companies', args: { sector: 'Utilities', metric: 'gap', limit: 2 } } },
        ] } }] });
        return Response.json({ candidates: [{ finishReason: 'STOP', content: { parts: [{ text: JSON.stringify({ answer: 'A is a priority [A]; its peer position is also elevated [A:company_benchmarks].', evidence_ids: ['A', 'A:company_benchmarks'], headline: 'One utility stands out', findings: ['A has the largest retrieved gap [A].'], recommended_actions: ['Review A’s transition plan.'], confidence: 'medium', follow_up_questions: ['Show A’s full evidence.'] }) }] } }] });
    };
    const execute = async path => path.startsWith('/api/companies?')
        ? Response.json({ data: [{ ticker: 'A', company_name: 'A Corp', gics_sector: 'Utilities', gap_pct_yr: 4 }], notes: ['Company note'], source: 'companies', page: {} })
        : Response.json({ data: [{ ticker: 'A', company_name: 'A Corp', gics_sector: 'Utilities', gap_pct_yr: 4, sector_percentile: 95 }], notes: ['Benchmark note'], source: 'benchmark', page: {} });
    const result = await answerQuestion({ question: 'Who should we engage?', context: { view: 'companies' }, history: [] }, env, execute, fetcher);
    assert.deepEqual(result.tool_calls, ['companies', 'company_benchmarks']);
    assert.equal(result.evidence.length, 2); assert.equal(result.brief.confidence, 'medium');
    assert.equal(result.visualization.type, 'company_table');
});
test('unsupported ownership question executes no database query', async () => {
    const r = await answerQuestion('Who owns this plume?', env, () => assert.fail(), model({ operation: 'unsupported', filters: [], tickers: [], message: 'No verified ownership links are available.' }));
    assert.equal(r.status, 'needs_clarification'); assert.equal(r.visualization, null);
});
test('invalid citations fall back to actual data', async () => {
    const r = await answerQuestion('test', env, async () => Response.json(data), model(plan, { answer: 'Invented [other]', evidence_ids: ['other'] }));
    assert.equal(r.status, 'data_only'); assert.equal(r.evidence.length, 1);
});
test('summary quota failure preserves results', async () => {
    const r = await answerQuestion('test', env, async () => Response.json(data), model(plan, new Response('', { status: 429 })));
    assert.equal(r.status, 'data_only');
});
test('planner quota failure is explicit', async () => {
    await assert.rejects(answerQuestion('test', env, () => assert.fail(), model(new Response('', { status: 429 }))), e => e.status === 429);
});
test('unknown tools, SQL filters, and excessive limits do not execute', async () => {
    await assert.rejects(answerQuestion('test', env, () => assert.fail(), model({ ...plan, operation: 'sql' })));
    await assert.rejects(answerQuestion('test', env, () => assert.fail(), model({ ...plan, filters: [{ key: 'limit', value: '201' }] })));
    await assert.rejects(answerQuestion('test', env, path => worker.fetch(new Request(`https://test${path}`), {}), model({ ...plan, filters: [{ key: 'sql', value: 'DROP TABLE companies' }] })), e => e.status === 422);
});
test('body limits, JSON and question validation', async () => {
    for (const body of ['bad json', '{}', JSON.stringify({ question: 'x'.repeat(1001) }), JSON.stringify({ question: 'ok', sql: 'bad' })]) {
        await assert.rejects(readQuestion(new Request('https://test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })));
    }
    await assert.rejects(readQuestion(new Request('https://test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: 'x'.repeat(9000) })), e => e.status === 413);
});
test('rate limiter blocks before AI calls', async () => {
    const r = await worker.fetch(new Request('https://test/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: 'test' }) }), { AI_RATE_LIMITER: { limit: async () => ({ success: false }) } });
    assert.equal(r.status, 429); assert.equal(r.headers.get('Retry-After'), '60');
});
test('GET ask is rejected', async () => {
    assert.equal((await worker.fetch(new Request('https://test/api/ask'), {})).status, 405);
});
