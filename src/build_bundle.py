"""Write site/data/bundle.js, the file:// fallback for the JSON data files.

Chrome and Firefox block fetch() of a local file, but a <script src> of one
still runs, so the page loads this instead when it is opened from file://.

The file list is read out of site/js/data.js rather than repeated here, so a
section agent who adds a data file to the FILES map gets it in the bundle
without knowing this script exists. Re-run after any change under site/data/:

    python3 src/build_bundle.py
"""
import json, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / 'site'

src = (SITE / 'js' / 'data.js').read_text()
block = re.search(r'var FILES = \{(.*?)\};', src, re.S)
if not block:
    raise SystemExit('could not find the FILES map in site/js/data.js')
files = dict(re.findall(r"(\w+)\s*:\s*'([^']+)'", block.group(1)))
if not files:
    raise SystemExit('the FILES map in site/js/data.js parsed to nothing')

parts = []
for key, rel in files.items():
    path = SITE / rel
    if not path.exists():
        raise SystemExit(f'{rel} is in the FILES map but not on disk')
    parts.append(json.dumps(key) + ':' + json.dumps(json.loads(path.read_text()),
                                                    separators=(',', ':')))

out = SITE / 'data' / 'bundle.js'
out.write_text('window.FILED_DATA={' + ','.join(parts) + '};\n')
print(f'{out.relative_to(ROOT)}  {out.stat().st_size / 1024:.0f} KB  '
      f'({len(files)} files: {", ".join(files)})')
