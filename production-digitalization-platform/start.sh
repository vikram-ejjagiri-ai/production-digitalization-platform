#!/usr/bin/env bash
# One-click start for macOS / Linux.  Run:  ./start.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "=========================================================="
echo "   Production Digitalization Platform - one-click start"
echo "=========================================================="

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Get Docker Desktop: https://www.docker.com/products/docker-desktop/"
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Starting Docker ..."
  [[ "$(uname)" == "Darwin" ]] && open -a Docker || true
  for _ in $(seq 1 36); do docker info >/dev/null 2>&1 && break; sleep 5; done
  docker info >/dev/null 2>&1 || { echo "Docker is not running. Start it and try again."; exit 1; }
fi

[[ -f .env ]] || { cp .env.example .env; echo "Created .env with default settings."; }

echo "[1/3] Building and starting all services (first run: 5-15 minutes) ..."
docker compose up -d --build

echo "[2/3] Preparing data and training the model (first run only) ..."
while [[ "$(docker compose ps -a --format '{{.State}}' trainer 2>/dev/null)" != "exited" ]]; do
  docker compose logs --tail 1 --no-log-prefix data-prep trainer 2>/dev/null | tail -1 | sed 's/^/    /'
  sleep 10
done
if [[ "$(docker compose ps -a --format '{{.ExitCode}}' trainer)" != "0" ]]; then
  echo "Data preparation or training failed:"; docker compose logs --tail 30 data-prep trainer; exit 1
fi

echo "[3/3] Waiting for the dashboards ..."
for _ in $(seq 1 60); do curl -fs http://localhost:3000/api/health >/dev/null && break; sleep 5; done

URL="http://localhost:3000/d/shopfloor"
(command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") || true
cat <<EOF

==========================================================
 Running!
   Shopfloor dashboard   http://localhost:3000/d/shopfloor
   Management dashboard  http://localhost:3000/d/management
   Compressor health     http://localhost:3000/d/asset-health
   Grafana login         admin / admin (only needed to edit)
   Commissioning report  reports/commissioning_report.html
   Database (Power BI)   localhost:5432 db=factory user=bi_reader pw=bi_reader

 Stop with ./stop.sh   Live logs with ./logs.sh
==========================================================
EOF
