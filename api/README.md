# Climate evidence API

Worker configured for the existing `climate-evidence` D1 database with binding `DB`. All database operations are read-only. `/api/ask` uses Gemini for query planning and evidence-based explanation.

Gemini uses native function calling with a fixed allowlist. The Worker validates the selected function arguments, executes its own read-only endpoint, and sends verified evidence back for the conclusion. Gemini never receives arbitrary SQL or unrestricted network access.

## Local setup

```sh
cd /Users/jimmy/Documents/ETHack2026/api
npm install
npm test
npx wrangler d1 execute climate-evidence --local --file=../data/d1/import.sql
npm run dev
```

The import above targets a fresh **local** database only. Do not reimport into your populated remote database. Tests require Node 22.13+ with `node:sqlite` and execute the SQL fixture in memory.

## Deploy

```sh
npx wrangler login
npm run check
npm run deploy
```

Use the Worker URL printed by Wrangler. Check `/api/health` after deployment; this reads both imported datasets. Set `ALLOWED_ORIGINS` in `wrangler.jsonc` to the exact deployed frontend origin before deploying, retaining localhost entries if desired. CORS limits browser access; this is a public, read-only API, not an authenticated service. No Cloudflare API key belongs in the browser. Database identifiers in the configuration are not secrets.

## Endpoints

All filters are optional, except ranking plumes by rate requires a gas selection. Unknown/duplicate parameters return 400. Pagination uses `limit` (default 50, maximum 200) and `offset`; follow `page.next_offset` until null. NULL values are preserved.

| Endpoint | Filters |
|---|---|
| `GET /api/health` | Database connectivity/schema probe |
| `GET /api/companies` | `sector` (exact GICS sector), `min_gap`, `sort=gap\|emissions\|risk\|name`, `limit`, `offset` |
| `GET /api/companies/:ticker` | Listing, emissions, financials, assessments; includes requested secondary listing if applicable |
| `GET /api/plumes` | `gas=CH4\|CO2`, `country`, `region`, `start`, `end`, `min_rate`, `west`, `east`, `south`, `north`, `sort=date\|rate`, `limit`, `offset` |

Dates use YYYY-MM-DD; start is inclusive, end exclusive. Country/region names match the export exactly (China is `People's Republic of China`). Viewport bounds must be supplied together. West greater than east represents an antimeridian crossing. `min_gap` is percentage points/year and `min_rate` is kg of the selected gas/hour. Company scope1_t is tonnes CO2e; d_ev_pct_of_ev is a stored scenario percentage. Source IDs and reporting dates accompany data, with interpretation notes in responses. These endpoints do not infer facility ownership or sum plume observations.

Examples:

```text
/api/companies?sector=Utilities&min_gap=0&limit=10
/api/companies/XOM
/api/plumes?gas=CH4&country=United%20States&region=Texas&start=2025-01-01&end=2026-01-01&sort=rate&limit=5
```

Frontend example (replace origin with the deployed Worker URL):

```js
const params = new URLSearchParams({ gas: 'CH4', region: 'Texas', sort: 'rate', limit: '5' });
const response = await fetch(`${API_ORIGIN}/api/plumes?${params}`);
const body = await response.json();
if (!response.ok) throw new Error(body.error);
// Use body.data plume_longitude/plume_latitude for map markers.
// Display gas, emission_auto, emission_uncertainty_auto and observed_at_utc.
```

## Ask the data

Store the key with `npx wrangler secret put GEMINI_API_KEY` (already done on the remote Worker). Never put it in frontend code. For local development, set it in ignored `.dev.vars`. `GEMINI_MODEL` defaults to `gemini-3.1-flash-lite` and can be changed in Wrangler configuration to a model enabled for your Google project.

```js
const response = await fetch(`${API_ORIGIN}/api/ask`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ question: 'Show the five largest methane plume observations in Texas during 2025.' })
});
const result = await response.json();
if (!response.ok) throw new Error(result.error);
// Render result.answer as text (not raw HTML).
// Draw result.visualization.points when visualization.type === 'map'.
// Allow inspection of result.evidence, queries, units and limitations.
```

Questions are standalone strings (maximum 1,000 characters). Supported: company screening, plume filtering, details/comparison for up to three explicit tickers, and proposed engagement questions. Lists return at most 20 records. Unsupported aggregates, ownership joins, annual totals, changed scenarios or ambiguous questions should return `needs_clarification`. No history, browsing, SQL generation or external tool execution is enabled.

The first model call produces a plan, checked by existing endpoint validators. Only the selected result rows are sent in the second call. Map points come from the database, never the model. Explanations must cite known evidence IDs or fall back to `data_only`; this validates citation references but does not prove every generated interpretation correct. Show evidence and limitations with every answer. NULL is preserved.

Responses have `status` (`ok`, `data_only`, `no_results`, `needs_clarification`), `answer`, `evidence`, and `visualization`. Data responses also include executed query paths, units, limitations and pagination. Visualization types are `map`, `company_table` and `company_details`; clarification returns null. HTTP 400/413/415 indicate invalid input, 422 an invalid translated filter, 429 rate/quota exhaustion, and 502/503 model/configuration/data availability problems. On summary failure, actual data remains available with a template answer.

AI requests use a shared 10/minute rate limiter **per Cloudflare location**, not a global billing cap. Each request makes at most two model calls with 25-second timeouts and no automatic retries. The public demo endpoint is not authenticated; provider quotas still apply. Requests and explanations are not persisted or cached by this Worker. Source text and user questions are treated as untrusted data.

Try:
- Show the five largest methane plume observations in Texas during 2025.
- Which five utilities have the largest positive target gaps?
- Compare XOM and CVX and suggest climate engagement questions.
- Who owns this plume? (should explain the missing ownership data)
