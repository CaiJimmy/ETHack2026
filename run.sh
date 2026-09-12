#!/bin/sh
# Regenerate synthetic data and serve the static site on http://localhost:8000
cd "$(dirname "$0")"
python3 data/generate.py
echo "open http://localhost:8000"
python3 -m http.server 8000 -d web
