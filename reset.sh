#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "This deletes the database, the data split, the trained model and the reports (data/raw is kept)."
read -r -p "Type YES to continue: " ok
[[ "$ok" == "YES" ]] || exit 0
docker compose --profile llm down -v
rm -f data/split/*.csv data/split/*.json models/*.joblib models/*.json reports/*.html reports/*.json
echo "Reset done. Run ./start.sh to start fresh."
