# Power BI management report

Grafana covers the real-time shopfloor view inside the one-click start. Power BI Desktop is a Windows application and can't run in Docker, so the management report connects to the same database from outside.

## Connect

1. Start the platform (`start.bat`).
2. Power BI Desktop → **Get data → PostgreSQL database**
   * Server: `localhost:5432`
   * Database: `factory`
   * Data connectivity mode: **DirectQuery** (live) or **Import** (faster, scheduled refresh)
3. Credentials: **Database**, user `bi_reader`, password `bi_reader` (read-only).
4. Select these tables / views:
   * `kpi.v_station_oee` – OEE per station and bucket
   * `kpi.v_station_oee_daily` – correctly aggregated daily OEE
   * `kpi.v_downtime_pareto` – downtime by station and reason
   * `kpi.line_kpis` – throughput, FPY, WIP, lead time per bucket
   * `kpi.order_lead_times` – one row per order (RFID)
   * `kpi.station_flow` – dwell and wait time per station
   * `kpi.v_alarm_log` – alarms with AI recommendations
   * `kpi.ai_summaries` – AI shift summaries
   * `master.stations` – dimension table (relate on `station_id`)

If the PostgreSQL connector asks for the Npgsql provider, recent Power BI Desktop versions include it. Otherwise install it from the link Power BI shows.

## Suggested DAX measures

```DAX
Availability = DIVIDE( SUM(v_station_oee[planned_s]) - SUM(v_station_oee[downtime_s]), SUM(v_station_oee[planned_s]) )

Quality = DIVIDE( SUM(v_station_oee[good_count]), SUM(v_station_oee[total_count]) )

Performance =
VAR run = SUM(v_station_oee[planned_s]) - SUM(v_station_oee[downtime_s])
VAR ideal = SUMX( v_station_oee, v_station_oee[total_count] * RELATED(stations[ideal_cycle_s]) )
RETURN MIN( 1, DIVIDE( ideal, run ) )

OEE = [Availability] * [Performance] * [Quality]

Avg Lead Time (min) = AVERAGE( order_lead_times[lead_time_s] ) / 60

Flow Efficiency = DIVIDE( SUM(order_lead_times[value_add_s]), SUM(order_lead_times[lead_time_s]) )
```

## Suggested report pages

1. **Overview:** OEE, FPY, throughput, lead time cards; OEE trend by station; AI summary text box.
2. **Losses:** downtime Pareto (bar), downtime by station × reason (stacked bar), MTBF/MTTR table.
3. **Material flow:** lead time distribution (histogram), flow efficiency trend, wait time before each station.
4. **Maintenance:** alarm log with recommended actions, health of compressor01.

Save the report as `dashboards/powerbi/production_kpis.pbix` and add screenshots to the README.
