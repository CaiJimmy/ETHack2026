#!/bin/sh
# Rebuild the master dataset (if .venv exists) and serve the site on http://localhost:8000 with caching disabled.
cd "$(dirname "$0")"
[ -x .venv/bin/python ] && .venv/bin/python data/build_master.py
python3 serve.py 8000
