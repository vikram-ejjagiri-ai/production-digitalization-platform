@echo off
cd /d "%~dp0"
echo Stopping all services (data is kept) ...
docker compose --profile llm down
echo Stopped. Start again with start.bat
pause
