# KPI definitions

One agreed definition per KPI, with its formula, data source and refresh rate, written down so that every dashboard and report computes the same number. Implemented in `services/kpi_engine/kpis.py` and unit tested in `tests/test_kpis.py`.

| KPI | Formula | Source | Granularity / refresh | Target |
|---|---|---|---|---|
| Planned time | Bucket length (from the first observed event; the running bucket ends at "now") | clock | per station and bucket / 30 s | – |
| Downtime | Overlap of stop intervals (`downtime_start` → `downtime_end`, open stops until now) with the bucket | `clean.line_events` | per station and bucket / 30 s | – |
| Run time | Planned time − downtime | derived | per station and bucket / 30 s | – |
| **Availability** | Run time / planned time | derived | per station and bucket / 30 s | ≥ 90 % |
| **Performance** | (Ideal cycle time × total count) / run time, capped at 100 % | `master.stations`, `cycle_end` events | per station and bucket / 30 s | ≥ 90 % |
| **Quality** | Good count / total count | `cycle_end.result` | per station and bucket / 30 s | ≥ 98 % |
| **OEE** | Availability × Performance × Quality | derived | per station and bucket / 30 s | ≥ 75 % |
| Line OEE | OEE of the bottleneck station (highest ideal cycle time, ST30) | derived | per bucket / 30 s | ≥ 75 % |
| **First pass yield** | Good completed orders / completed orders | `order_completed` events | per bucket / 30 s | ≥ 97 % |
| Throughput | Good parts per hour of planned time | `order_completed` events | per bucket / 30 s | – |
| WIP | Orders released − orders completed | `order_released`, `order_completed` | end of bucket / 30 s | ≤ 12 (CONWIP) |
| **MTBF** | Run time / number of stops | `downtime_start` | per station / 30 s | – |
| **MTTR** | Downtime / number of stops | stop intervals | per station / 30 s | – |
| **Lead time** | Last RFID read − first RFID read of the order | `clean.rfid_reads` | per order | – |
| Value-adding time | Σ over stations of (first OUT read − first IN read) | RFID | per order | – |
| Waiting time | Lead time − value-adding time | RFID | per order | – |
| Flow efficiency | Value-adding time / lead time | RFID | per order | – |
| Dwell time per station | First OUT read − first IN read at that station | RFID | per station and bucket | – |
| Wait before station | IN read at the station − OUT read at the previous station | RFID | per station and bucket | – |
| Machine health | Ensemble health score (0–100) vs commissioning baseline | `clean.sensor_readings` | every minute of machine time | ≥ 70 |
| Data quality | Rejected messages, duplicate RFID reads removed, flagged sensor rows | `raw.*` vs `clean.*` | per bucket / 30 s | 0 rejected |

## Notes and conventions

* **Aggregating OEE over longer periods.** Averaging bucket OEE values is wrong when buckets differ in length or volume. The views and dashboards sum the components first (Σ run / Σ planned, Σ ideal × count / Σ run, Σ good / Σ total) and multiply afterwards. See `kpi.v_station_oee_daily`.
* **Scrap** is counted at the station where it happens. Scrapped parts leave the line and count as completed with result `scrap`.
* **Planned time** assumes 24/7 operation. A shift calendar (breaks, planned maintenance) would be the next refinement and would go into `master`.
* **Time zone.** Everything is stored in UTC, and Grafana displays it in the browser's time zone.
* **Late data.** The KPI engine recomputes the last `KPI_LOOKBACK_HOURS` (3 h) on every run.
