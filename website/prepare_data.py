"""Generate the browse snapshot from the same inputs as D1. AI queries use the live API."""
import csv, json, sqlite3
from pathlib import Path
root = Path(__file__).resolve().parents[1]
db = sqlite3.connect(':memory:')
db.row_factory = sqlite3.Row
db.executescript((root/'data/d1/import.sql').read_text())
out = Path(__file__).parent/'public/data'
out.mkdir(parents=True,exist_ok=True)
columns = 'plume_id,plume_latitude,plume_longitude,observed_at_utc,country,region,place,ipcc_sector,gas,emission_auto,emission_uncertainty_auto,bounds_west,bounds_south,bounds_east,bounds_north,platform,provider'
plumes=[dict(r) for r in db.execute('SELECT '+columns+' FROM plume_observations')]
companies=[dict(r) for r in db.execute('SELECT s.*, f.market_cap_musd FROM company_screening s JOIN company_financials f USING(ticker)')]
assert len(plumes)==12936 and len(companies)==500
(out/'snapshot.json').write_text(json.dumps({'plumes':plumes,'companies':companies,'built_at':'2026-09-12','observation_year':2025},separators=(',',':')))
print('Prepared',len(plumes),'observations and',len(companies),'companies')
