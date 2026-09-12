#!/bin/sh
# Rebuild the master dataset (needs .venv with openpyxl) and serve the site on http://localhost:8000
cd "$(dirname "$0")"
[ -x .venv/bin/python ] && .venv/bin/python data/build_master.py
echo "open http://localhost:8000"
python3 -m http.server 8000 -d web
