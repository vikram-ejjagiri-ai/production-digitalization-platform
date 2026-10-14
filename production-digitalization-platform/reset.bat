@echo off
cd /d "%~dp0"
echo This deletes the database, the data split, the trained model and the reports.
echo The downloaded raw dataset in data\raw is kept.
set /p ok=Type YES to continue: 
if /i not "%ok%"=="YES" exit /b 0
docker compose --profile llm down -v
del /q data\split\*.csv data\split\*.json models\*.joblib models\*.json reports\*.html reports\*.json 2>nul
echo Reset done. Run start.bat to start fresh.
pause
