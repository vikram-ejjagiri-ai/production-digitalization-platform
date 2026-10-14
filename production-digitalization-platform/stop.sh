#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "Stopping all services (data is kept) ..."
docker compose --profile llm down
