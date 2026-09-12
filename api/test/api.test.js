import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import worker from '../src/index.js';

const sqlite = new DatabaseSync(':memory:');
sqlite.exec(readFileSync(new URL('../../data/d1/import.sql', import.meta.url), 'utf8'));
const env = {
    ALLOWED_ORIGINS: 'http://localhost:8000', DB: {
        prepare(sql) {
            const stmt = sqlite.prepare(sql);
            const bound = (values) => ({
                all: async () => ({ results: stmt.all(...values) }),
                first: async () => stmt.get(...values) ?? null,
            });
            return { ...bound([]), bind: (...values) => bound(values) };
        },
    }
};
const call = (path, options) => worker.fetch(new Request('https://api.example' + path, options), env);

test('health verifies imported tables', async () => {
    assert.equal((await call('/api/health')).status, 200);
});
test('primary-only pagination returns exactly 500 unique companies', async () => {
    const rows = [];
    for (let offset = 0; offset !== null;) {
        const body = await (await call(`/api/companies?limit=200&offset=${offset}`)).json();
        rows.push(...body.data); offset = body.page.next_offset;
    }
    assert.equal(rows.length, 500); assert.equal(new Set(rows.map(r => r.ticker)).size, 500);
    assert.ok(!rows.some(r => r.ticker === 'GOOG'));
});
test('company filter applies positive gap and sector', async () => {
    const { data } = await (await call('/api/companies?sector=Utilities&min_gap=0')).json();
    assert.ok(data.length > 0);
    assert.ok(data.every(r => r.gics_sector === 'Utilities' && r.gap_pct_yr >= 0));
});
test('detail preserves leading zeros and missing emissions', async () => {
    const { data } = await (await call('/api/companies/a')).json();
    assert.equal(data.listing.cik, '0001090872'); assert.equal(data.emissions.scope1_t, null);
    assert.equal((await call('/api/companies/UNKNOWN')).status, 404);
});
test('plume ranked query agrees with independent source SQL', async () => {
    const { data } = await (await call('/api/plumes?gas=CH4&country=United%20States&region=Texas&start=2025-01-01&end=2026-01-01&sort=rate&limit=5')).json();
    const expected = sqlite.prepare("SELECT plume_id FROM plume_observations WHERE gas='CH4' AND country='United States' AND region='Texas' AND emission_auto IS NOT NULL ORDER BY emission_auto DESC,plume_id LIMIT 5").all();
    assert.equal(data.length, 5); assert.deepEqual(data.map(r => r.plume_id), expected.map(r => r.plume_id));
});
test('antimeridian viewport excludes central longitudes', async () => {
    const { data } = await (await call('/api/plumes?west=170&east=-170&south=-90&north=90')).json();
    assert.ok(data.every(r => r.plume_longitude >= 170 || r.plume_longitude <= -170));
});
test('invalid filters are rejected', async () => {
    for (const path of ['/api/plumes?sort=rate', '/api/plumes?gas=NO2', '/api/plumes?start=2025-02-30', '/api/plumes?west=10', '/api/companies?limit=201', '/api/companies?limit=', '/api/companies?limit=2&limit=3', '/api/companies?sort=toString', '/api/plumes?end=2025-01-01&start=2025-12-01', '/api/companies?sql=DROP']) {
        assert.equal((await call(path)).status, 400, path);
    }
});
test('SQL injection text is treated as a literal', async () => {
    const { data } = await (await call('/api/companies?sector=' + encodeURIComponent("Utilities' OR 1=1 --"))).json();
    assert.deepEqual(data, []);
});
test('CORS and methods', async () => {
    assert.equal((await call('/api/companies', { method: 'POST' })).status, 405);
    assert.equal((await call('/api/companies', { headers: { Origin: 'https://unknown.example' } })).status, 403);
    const r = await call('/api/companies', { method: 'OPTIONS', headers: { Origin: 'http://localhost:8000' } });
    assert.equal(r.status, 204); assert.equal(r.headers.get('Access-Control-Allow-Origin'), 'http://localhost:8000');
});
test('database errors do not leak SQL', async () => {
    const response = await worker.fetch(new Request('https://api.example/api/health'), { DB: { prepare() { throw Error('secret SQL'); } } });
    assert.equal(response.status, 503); assert.equal((await response.json()).error, 'Data service unavailable');
});
