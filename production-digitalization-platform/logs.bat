@echo off
cd /d "%~dp0"
echo Live logs of all services. Close this window to stop watching (services keep running).
docker compose logs -f --tail 30
