#!/usr/bin/env bash
# Build and publish the web app.
#
# Two rewrites only matter in a production build and a plain `npm run build`
# will undo them every time, which is why this is a script and not a habit:
#   1. the app is served from /app, and an absolute /data/... path is not
#      rewritten by vite's base, so it has to be patched after the build;
#   2. /api/ask is still relative in source, so it would resolve against our
#      own origin rather than the worker. /api/companies is already absolute
#      upstream and needs nothing.
set -euo pipefail
cd "$(dirname "$0")/.."

WORKER="https://climate-evidence-api.jimmycai.workers.dev"
HOST="tyro@195.15.203.200"

( cd website && npm run build )
sed -i "s|\"/data/|\"/app/data/|g; s|\"/api/ask\"|\"$WORKER/api/ask\"|g" website/dist/assets/*.js

rsync -az --delete website/dist/ "$HOST:/var/www/ethack/app/"
rsync -az landing/index.html "$HOST:/var/www/ethack/index.html"

echo "deployed. verifying:"
for u in "" "app/" "filed/"; do
  printf "  /%-7s %s\n" "$u" "$(curl -s -o /dev/null -w 'HTTP %{http_code}' --max-time 20 "https://ethack.tyrolize.ch/$u")"
done
