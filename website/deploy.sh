#!/usr/bin/env bash
# Build and ship the app to https://ethack.tyrolize.ch/app/
#
# The bundle is served from a subpath, so two rewrites have to happen after
# every build. A plain `npm run build` undoes both, which is why they live
# here rather than in anyone's memory.
#   1. the data fetches are absolute /data/..., and the site root is /app/
#   2. /api/ask has no origin on the static host, so it points at the worker
set -euo pipefail
cd "$(dirname "$0")"

npm run build
sed -i 's|"/data/|"/app/data/|g' dist/assets/*.js
sed -i 's|"/api/ask"|"https://climate-evidence-api.jimmycai.workers.dev/api/ask"|g' dist/assets/*.js

if grep -q '"/data/' dist/assets/*.js; then
  echo "a bare /data/ path survived the rewrite" >&2
  exit 1
fi

rsync -az --delete dist/ tyro@195.15.203.200:/var/www/ethack/app/
curl -sf -o /dev/null -w 'https://ethack.tyrolize.ch/app/ %{http_code}\n' https://ethack.tyrolize.ch/app/
