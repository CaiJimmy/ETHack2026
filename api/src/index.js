import { AskError, readQuestion, answerQuestion } from './ask.js';
class InputError extends Error { }
const fail = (message) => { throw new InputError(message); };
function number(p, key, fallback, min, max, integer = false) {
    if (!p.has(key)) return fallback;
    const raw = p.get(key);
    const n = raw.trim() === '' ? NaN : Number(raw);
    if (!Number.isFinite(n) || n < min || n > max || (integer && !Number.isInteger(n))) fail(`Invalid ${key}`);
    return n;
}
function validate(p, allowed) {
    for (const key of p.keys()) {
        if (!allowed.includes(key)) fail(`Unknown parameter: ${key}`);
        if (p.getAll(key).length !== 1 || p.get(key).length > 200 || !p.get(key).trim()) fail(`Invalid ${key}`);
    }
}
function date(p, key) {
    if (!p.has(key)) return null;
    const value = p.get(key);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) fail(`${key} must be YYYY-MM-DD`);
    const d = new Date(`${value}T00:00:00Z`);
    if (!Number.isFinite(d.getTime()) || d.toISOString().slice(0, 10) !== value) fail(`Invalid ${key}`);
    return d.toISOString().replace('.000Z', 'Z');
}
function page(p) {
    return { limit: number(p, 'limit', 50, 1, 200, true), offset: number(p, 'offset', 0, 0, 100000, true) };
}
export function companyQuery(p) {
    validate(p, ['sector', 'min_gap', 'sort', 'limit', 'offset']);
    const { limit, offset } = page(p), where = [], values = [];
    if (p.has('sector')) { where.push('gics_sector = ?'); values.push(p.get('sector')); }
    if (p.has('min_gap')) { where.push('gap_pct_yr >= ?'); values.push(number(p, 'min_gap', null, -1000, 1000)); }
    const sorts = { gap: 'gap_pct_yr DESC', emissions: 'scope1_t DESC', risk: 'd_ev_pct_of_ev DESC', name: 'company_name ASC' };
    const sort = p.get('sort') || 'gap';
    if (!Object.hasOwn(sorts, sort)) fail('Invalid sort');
    return { sql: `SELECT * FROM company_screening ${where.length ? 'WHERE ' + where.join(' AND ') : ''} ORDER BY ${sorts[sort]}, ticker ASC LIMIT ? OFFSET ?`, values: [...values, limit + 1, offset], limit, offset };
}
export function plumeQuery(p) {
    validate(p, ['gas', 'country', 'region', 'start', 'end', 'min_rate', 'west', 'east', 'south', 'north', 'sort', 'limit', 'offset']);
    const { limit, offset } = page(p), where = [], values = [];
    for (const key of ['gas', 'country', 'region']) {
        if (p.has(key)) {
            if (key === 'gas' && !['CH4', 'CO2'].includes(p.get(key))) fail('gas must be CH4 or CO2');
            where.push(`${key} = ?`); values.push(p.get(key));
        }
    }
    const start = date(p, 'start'), end = date(p, 'end');
    if (start && end && start >= end) fail('end must be after start (end is exclusive)');
    if (start) { where.push('observed_at_utc >= ?'); values.push(start); }
    if (end) { where.push('observed_at_utc < ?'); values.push(end); }
    if (p.has('min_rate')) { where.push('emission_auto >= ?'); values.push(number(p, 'min_rate', null, 0, 1e15)); }
    const bounds = ['west', 'east', 'south', 'north'];
    if (bounds.some(k => p.has(k))) {
        if (!bounds.every(k => p.has(k))) fail('Provide all four viewport bounds');
        const w = number(p, 'west', null, -180, 180), e = number(p, 'east', null, -180, 180);
        const s = number(p, 'south', null, -90, 90), n = number(p, 'north', null, -90, 90);
        if (s > n) fail('south must not exceed north');
        where.push('plume_latitude BETWEEN ? AND ?'); values.push(s, n);
        where.push(w <= e ? 'plume_longitude BETWEEN ? AND ?' : '(plume_longitude >= ? OR plume_longitude <= ?)'); values.push(w, e);
    }
    const sort = p.get('sort') || 'date';
    if (!['date', 'rate'].includes(sort)) fail('Invalid sort');
    if (sort === 'rate') {
        if (!p.has('gas')) fail('Choose gas when ranking emission rates');
        where.push('emission_auto IS NOT NULL');
    }
    return { sql: `SELECT plume_id, plume_latitude, plume_longitude, observed_at_utc, country, region, place, ipcc_sector, gas, emission_auto, emission_uncertainty_auto, bounds_west, bounds_south, bounds_east, bounds_north, platform, provider FROM plume_observations ${where.length ? 'WHERE ' + where.join(' AND ') : ''} ORDER BY ${sort === 'rate' ? 'emission_auto' : 'observed_at_utc'} DESC, plume_id ASC LIMIT ? OFFSET ?`, values: [...values, limit + 1, offset], limit, offset };
}
export function benchmarkQuery(p) {
    validate(p, ['sector', 'ticker', 'metric', 'limit', 'offset']);
    const { limit, offset } = page(p), where = [], values = [];
    const metrics = { gap: 'gap_pct_yr', emissions: 'scope1_t', risk: 'd_ev_pct_of_ev' };
    const metric = p.get('metric') || 'gap', column = metrics[metric];
    if (!column) fail('Invalid metric');
    if (p.has('sector')) { where.push('gics_sector = ?'); values.push(p.get('sector')); }
    if (p.has('ticker')) {
        const ticker = p.get('ticker').toUpperCase();
        if (!/^[A-Z0-9.-]{1,15}$/.test(ticker)) fail('Invalid ticker');
        where.push('ticker = ?'); values.push(ticker);
    }
    return { sql: `WITH ranked AS (
        SELECT *, AVG(${column}) OVER (PARTITION BY gics_sector) AS sector_average,
          COUNT(${column}) OVER (PARTITION BY gics_sector) AS sector_peer_count,
          100.0 * PERCENT_RANK() OVER (PARTITION BY gics_sector ORDER BY ${column}) AS sector_percentile
        FROM company_screening WHERE ${column} IS NOT NULL
      ) SELECT *, ? AS benchmark_metric FROM ranked ${where.length ? 'WHERE ' + where.join(' AND ') : ''}
      ORDER BY ${column} DESC, ticker ASC LIMIT ? OFFSET ?`, values: [metric, ...values, limit + 1, offset], limit, offset };
}
export function hotspotQuery(p) {
    validate(p, ['gas', 'country', 'region', 'start', 'end', 'min_rate', 'min_observations', 'sort', 'limit', 'offset']);
    const { limit, offset } = page(p), where = [], values = [];
    const gas = p.get('gas');
    if (!['CH4', 'CO2'].includes(gas)) fail('gas must be CH4 or CO2');
    where.push('gas = ?'); values.push(gas);
    for (const key of ['country', 'region']) if (p.has(key)) { where.push(`${key} = ?`); values.push(p.get(key)); }
    const start = date(p, 'start'), end = date(p, 'end');
    if (start && end && start >= end) fail('end must be after start (end is exclusive)');
    if (start) { where.push('observed_at_utc >= ?'); values.push(start); }
    if (end) { where.push('observed_at_utc < ?'); values.push(end); }
    if (p.has('min_rate')) { where.push('emission_auto >= ?'); values.push(number(p, 'min_rate', null, 0, 1e15)); }
    const minimum = number(p, 'min_observations', 2, 2, 1000, true);
    const sort = p.get('sort') || 'count';
    if (!['count', 'rate'].includes(sort)) fail('Invalid sort');
    return { sql: `SELECT gas || ':' || printf('%.1f', ROUND(plume_latitude,1)) || ':' || printf('%.1f', ROUND(plume_longitude,1)) AS plume_id,
        ROUND(plume_latitude,1) AS plume_latitude, ROUND(plume_longitude,1) AS plume_longitude,
        MAX(country) AS country, MAX(region) AS region, COALESCE(MAX(place), MAX(region), MAX(country), 'Hotspot') AS place,
        gas, COUNT(*) AS observation_count, COUNT(emission_auto) AS quantified_count,
        MAX(emission_auto) AS emission_auto, AVG(emission_auto) AS average_emission_rate,
        MIN(observed_at_utc) AS first_observed_at, MAX(observed_at_utc) AS observed_at_utc,
        'Approximately 0.1 degree grid; observations are not unique facilities' AS aggregation_basis,
        'Carbon Mapper' AS provider
      FROM plume_observations WHERE ${where.join(' AND ')}
      GROUP BY gas, ROUND(plume_latitude,1), ROUND(plume_longitude,1) HAVING COUNT(*) >= ?
      ORDER BY ${sort === 'rate' ? 'emission_auto' : 'observation_count'} DESC, plume_id ASC LIMIT ? OFFSET ?`, values: [...values, minimum, limit + 1, offset], limit, offset };
}
const companyNotes = ['Primary listings only in screening results.', 'Reporting years and emissions boundaries vary.', 'Risk values are stored scenario estimates, not predictions.'];
const plumeNotes = ['Rows are observations, not unique facilities.', 'NULL rates mean unquantified, not zero.', 'Rates are kg of the specified gas/hour, not annual emissions.', 'Bounds enclose plume imagery; ownership is not established.'];
const benchmarkNotes = ['Percentiles and averages compare companies only with peers in the same GICS sector that have the selected metric.', 'A high gap percentile means reductions are slower relative to the stated promise.', ...companyNotes.slice(1)];
const hotspotNotes = ['A hotspot groups observations whose coordinates round to the same 0.1° cell (about 11 km north-south); it is not a facility or ownership attribution.', 'Repeated observations may cover the same event on different dates or passes.', ...plumeNotes.slice(1)];
async function list(db, query, notes, source) {
    const result = await db.prepare(query.sql).bind(...query.values).all();
    const more = result.results.length > query.limit;
    return { data: result.results.slice(0, query.limit), page: { limit: query.limit, offset: query.offset, next_offset: more ? query.offset + query.limit : null }, source, notes };
}
const worker = {
    async fetch(request, env) {
        const url = new URL(request.url), origin = request.headers.get('Origin');
        const allowed = (env.ALLOWED_ORIGINS || '').split(',').map(s => s.trim());
        const headers = { 'Vary': 'Origin', 'X-Content-Type-Options': 'nosniff' };
        if (origin && (origin === url.origin || allowed.includes(origin))) {
            headers['Access-Control-Allow-Origin'] = origin;
            headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS';
            headers['Access-Control-Allow-Headers'] = 'Content-Type';
        }
        const reply = (body, status = 200) => Response.json(body, { status, headers });
        if (origin && !headers['Access-Control-Allow-Origin']) return reply({ error: 'Origin not allowed' }, 403);
        if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers });
        const ask = url.pathname === '/api/ask';
        if (request.method !== (ask ? 'POST' : 'GET')) return Response.json({ error: 'Method not allowed' }, { status: 405, headers: { ...headers, Allow: ask ? 'POST, OPTIONS' : 'GET, OPTIONS' } });
        try {
            if (ask) {
                headers['Cache-Control'] = 'no-store';
                validate(url.searchParams, []);
                const question = await readQuestion(request);
                if (!env.AI_RATE_LIMITER) throw new AskError('AI rate limiter is not configured', 503);
                const { success } = await env.AI_RATE_LIMITER.limit({ key: 'climate-evidence-ask' });
                if (!success) { headers['Retry-After'] = '60'; throw new AskError('Too many AI requests. Try again in a minute.', 429); }
                return reply(await answerQuestion(question, env, path => worker.fetch(new Request(`${url.origin}${path}`), env)));
            }
            if (url.pathname === '/api/health') {
                await env.DB.prepare('SELECT ticker FROM companies LIMIT 1').first();
                await env.DB.prepare('SELECT plume_id FROM plume_observations LIMIT 1').first();
                return reply({ status: 'ok', database: 'climate-evidence' });
            }
            if (url.pathname === '/api/companies') return reply(await list(env.DB, companyQuery(url.searchParams), companyNotes, 'company_screening'));
            if (url.pathname === '/api/plumes') return reply(await list(env.DB, plumeQuery(url.searchParams), plumeNotes, 'plume_observations'));
            if (url.pathname === '/api/insights/company-benchmarks') return reply(await list(env.DB, benchmarkQuery(url.searchParams), benchmarkNotes, 'company_screening + sector window functions'));
            if (url.pathname === '/api/insights/hotspots') return reply(await list(env.DB, hotspotQuery(url.searchParams), hotspotNotes, 'plume_observations grouped to 0.1 degree cells'));
            const match = url.pathname.match(/^\/api\/companies\/([^/]+)$/);
            if (match) {
                validate(url.searchParams, []);
                let ticker;
                try { ticker = decodeURIComponent(match[1]).toUpperCase(); } catch { fail('Invalid ticker'); }
                if (!/^[A-Z0-9.-]{1,15}$/.test(ticker)) fail('Invalid ticker');
                const listing = await env.DB.prepare('SELECT * FROM company_listings WHERE ticker = ?').bind(ticker).first();
                if (!listing) return reply({ error: 'Company not found' }, 404);
                const data = { listing };
                for (const group of ['emissions', 'financials', 'assessments']) {
                    data[group] = await env.DB.prepare(`SELECT * FROM company_${group} WHERE ticker = ?`).bind(ticker).first();
                }
                return reply({ data, source: { ticker, tables: ['company_listings', 'company_emissions', 'company_financials', 'company_assessments'] }, notes: ['Detail includes the requested share class; inspect is_primary_listing before aggregation.', ...companyNotes.slice(1), 'No verified plume ownership links available.'] });
            }
            return reply({ error: 'Endpoint not found' }, 404);
        } catch (error) {
            if (error instanceof AskError) return reply({ error: error.message }, error.status);
            if (error instanceof InputError) return reply({ error: error.message }, 400);
            console.error('Database request failed');
            return reply({ error: 'Data service unavailable' }, 503);
        }
    }
};
export default worker;
