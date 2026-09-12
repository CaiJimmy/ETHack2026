# Fieldwork — first MVP

Independent React/Vite frontend, created from scratch. Teammates' experimental frontends are untouched.

Current delivery: local MVP. Public deployment was not performed because automatic approval review requires explicit permission to publish the bundled dataset to this new app.

## Run

```sh
cd jimmy-website
npm install
npm run dev
```

Vite prints the available local port (5173 by default). `/api/*` is proxied to the existing `climate-evidence-api.jimmycai.workers.dev` Worker, so no browser secrets or manual CORS changes are needed.

## Build and deploy

```sh
npm run build
npm run deploy
```

The separate `jimmy-website` Cloudflare Worker serves built assets and proxies only `/api/*` to the existing API. It does not create or modify D1, store Gemini credentials, or replace the backend. Wrangler authentication must be available. The frontend proxy accepts same-origin browser requests. The upstream API's shared AI rate limits remain in force.

## Features

- Global map of 12,936 Carbon Mapper plume observations. Gas, country, sector, date and minimum-rate filters; zoom clusters; individual rates; keyboard-accessible record list; evidence drawer.
- Company treemap grouped by sector, switching between market capitalization and Scope 1 emissions. Tiles open evidence. Sector legend filters the selection. Missing values have no tile area and their count is explicit.
- Company logos in the treemap, screening table and evidence drawer. Unavailable logos fall back to sector-colored ticker monograms.
- 500 primary-company screening table and promises-versus-delivery scatterplot. Sector/name/gap filters, sorting and incremental rows. Scatterplot uses the 108 records with a stored gap and both input rates; it does not invent gaps for other records.
- Gemini question box using the live `/api/ask`. Cited records open evidence; returned filters update the map/table. Shows loading, failure, no-result, unsupported-question and data-only fallback states.
- Live company detail retrieval, scenario assumptions, reporting windows, emissions coverage and engagement-question shortcut.
- Responsive desktop/mobile layouts, native modal focus handling, keyboard controls, reduced-motion support, readable empty/error states.

## Data and interpretation

The browse dataset in `public/data/snapshot.json` is generated from the same import used for D1. It includes all 12,936 plume observations and 500 primary companies, not sample data. The browser uses this dated snapshot for responsive filtering and full-world clustering; AI answers and company details query the live API. Changes in D1 do not automatically refresh the browse snapshot.

Rebuild the snapshot from the SQL import:

```sh
python3 jimmy-website/prepare_data.py
```

The snapshot includes an extra market-cap field for treemap sizing. Financial values retain the master source's units (USD millions). Treemap percentages are shares of the selected, available values. Scope 1 combines years and boundaries, and missing emissions are not zero. Tiny tiles remain accessible through the table and search.

Plume rates are kg of the specified gas per hour. Clusters count observations, not facilities. This is not an annual inventory or a map of all emissions. No company ownership is inferred. Map tiles come from CARTO/OpenStreetMap with attribution; fonts are Google Fonts with local fallbacks. An internet connection is needed for basemap tiles and AI. The snapshot can still be browsed when the AI is unavailable.

Company logos load at runtime from Financial Modeling Prep's public ticker image endpoint; they are not bundled into the repository. The fallback keeps every company identifiable if an image is missing or the service is offline. Confirm third-party logo usage terms before a public production release.

## Checked

Production build; desktop and 390px mobile layout; no mobile document overflow; live methane question populates five map results; source citation opens rate/date/uncertainty; company drawer loads live D1 details; scatterplot renders the stored comparable sample; treemap switches from 500 market-cap records to 319 Scope 1 records with 181 missing values reported.
