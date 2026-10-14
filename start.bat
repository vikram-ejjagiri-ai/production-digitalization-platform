@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Production Digitalization Platform
echo.
echo  ==========================================================
echo     Production Digitalization Platform - one-click start
echo  ==========================================================
echo.

where docker >nul 2>nul
if errorlevel 1 (
    echo  Docker is not installed.
    echo  Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and run this again.
    pause
    exit /b 1
)

docker info >nul 2>nul
if not errorlevel 1 goto docker_ready
echo  Starting Docker Desktop ...
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set /a tries=0
:wait_docker
timeout /t 5 /nobreak >nul
docker info >nul 2>nul
if not errorlevel 1 goto docker_ready
set /a tries+=1
if !tries! geq 36 (
    echo  Docker did not start within 3 minutes. Start Docker Desktop manually and run this again.
    pause
    exit /b 1
)
goto wait_docker

:docker_ready
if not exist .env (
    copy .env.example .env >nul
    echo  Created .env with default settings.
)

echo  [1/3] Building and starting all services (first run: 5-15 minutes) ...
docker compose up -d --build
if errorlevel 1 (
    echo  Docker Compose failed - see the messages above.
    pause
    exit /b 1
)

echo.
echo  [2/3] Preparing data and training the model (first run only) ...
:wait_pipeline
set "TSTATE="
for /f "delims=" %%s in ('docker compose ps -a --format "{{.State}}" trainer 2^>nul') do set "TSTATE=%%s"
if /i "!TSTATE!"=="exited" goto pipeline_done
for /f "delims=" %%l in ('docker compose logs --tail 1 --no-log-prefix data-prep trainer 2^>nul') do set "LAST=%%l"
if defined LAST echo     !LAST!
timeout /t 10 /nobreak >nul
goto wait_pipeline

:pipeline_done
set "TEXIT=1"
for /f "delims=" %%e in ('docker compose ps -a --format "{{.ExitCode}}" trainer') do set "TEXIT=%%e"
if not "!TEXIT!"=="0" (
    echo  Data preparation or training failed. Last log lines:
    docker compose logs --tail 30 data-prep trainer
    pause
    exit /b 1
)

echo.
echo  [3/3] Waiting for the dashboards ...
powershell -NoProfile -Command "$i=0; while($i -lt 60){ try { $r = Invoke-WebRequest -UseBasicParsing http://localhost:3001/api/health -TimeoutSec 3; if($r.StatusCode -eq 200){ exit 0 } } catch {}; Start-Sleep 5; $i++ }; exit 1"
if errorlevel 1 (
    echo  Grafana did not respond. Check: docker compose logs grafana
    pause
    exit /b 1
)

start "" "http://localhost:3001/d/shopfloor"
echo.
echo  ==========================================================
echo   Running!
echo     Shopfloor dashboard   http://localhost:3001/d/shopfloor
echo     Management dashboard  http://localhost:3001/d/management
echo     Compressor health     http://localhost:3001/d/asset-health
echo     Grafana login         admin / admin  (only needed to edit)
echo     Commissioning report  reports\commissioning_report.html
echo     Database (Power BI)   localhost:5432  db=factory  user=bi_reader  pw=bi_reader
echo.
echo   Stop with stop.bat. Live logs with logs.bat.
echo  ==========================================================
start "" "reports\commissioning_report.html"
pause
