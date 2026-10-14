# Data dictionary

## Machine signals: `clean.sensor_readings` (compressor01, MetroPT-3)

| Column | Unit | Type | Meaning |
|---|---|---|---|
| `ts` | – | timestamptz | Time the reading was published (UTC) |
| `source_ts` | – | timestamp | Original timestamp in the dataset |
| `tp2` | bar | analog | Pressure on the compressor |
| `tp3` | bar | analog | Pressure at the pneumatic panel |
| `h1` | bar | analog | Pressure drop when the cyclonic separator filter discharges |
| `dv_pressure` | bar | analog | Pressure drop when the air dryer towers discharge; 0 = compressor under load |
| `reservoirs` | bar | analog | Downstream reservoir pressure; should be close to TP3 |
| `oil_temperature` | °C | analog | Compressor oil temperature |
| `motor_current` | A | analog | One motor phase: ≈0 A off, ≈4 A offloaded, ≈7 A loaded, ≈9 A starting |
| `comp` | 0/1 | digital | Air intake valve signal; active when there is no air intake (off or offloaded) |
| `dv_electric` | 0/1 | digital | Compressor outlet valve; active when under load |
| `towers` | 0/1 | digital | Which dryer tower is active |
| `mpg` | 0/1 | digital | Starts the compressor under load when pressure < 8.2 bar |
| `lps` | 0/1 | digital | Low pressure switch, active below 7 bar |
| `pressure_switch` | 0/1 | digital | Detects discharge in the drying towers |
| `oil_level` | 0/1 | digital | Active when oil is below the expected level |
| `caudal_impulses` | 0/1 | digital | Pulses of air flow from the APU to the reservoirs |
| `dq_flag` | – | text | NULL = OK, otherwise e.g. `oil_temperature_out_of_range` |

Signal descriptions follow the dataset documentation on UCI. The dataset column `DV_eletric` is renamed to `dv_electric`.

## Production events: `clean.line_events`

| Column | Meaning |
|---|---|
| `ts` | Event time (UTC) |
| `station_id` | Canonical station ID `ST10` to `ST50` (see `master.stations`) |
| `event_type` | `order_released`, `cycle_start`, `cycle_end`, `downtime_start`, `downtime_end`, `order_completed` |
| `order_id` | Production order, e.g. `ORD-261014-00042` |
| `duration_s` | Cycle or stop duration in seconds (harmonized from ms where needed) |
| `result` | `good` / `scrap` for `cycle_end` and `order_completed` |
| `reason` | Stop reason: `material_missing`, `tool_change`, `machine_fault`, `quality_check`, `operator_absent`, `low_air_pressure` |

## RFID: `clean.rfid_reads`

| Column | Meaning |
|---|---|
| `ts` | Read time (UTC) |
| `epc` | Tag ID (EPC, hex) of the part carrier |
| `order_id` | Order linked to the carrier |
| `station_id` | Canonical station, parsed from the reader name `RDR-ST30-IN` |
| `direction` | `in` / `out` |
| `rssi` | Signal strength in dBm |

## Machine health and alarms

| Table | Key columns |
|---|---|
| `clean.machine_health` | `health_score` (0–100), `health_forest`, `health_zscore`, `status` (`normal` / `warning` / `alarm`), `contributors` (top 5 deviating features as JSON) |
| `clean.alarms` | `alarm_id`, `opened_at`, `closed_at`, `source_ts_open` (dataset time), `min_health`, `contributors`, `status` |
| `clean.ai_recommendations` | `alarm_id`, `provider`, `likely_cause`, `recommended_actions` (JSON list), `urgency`, `confidence`, `evidence`, `knowledge_sources` |

## KPI tables

See [kpi_definitions.md](kpi_definitions.md). The tables are `kpi.station_kpis`, `kpi.line_kpis`, `kpi.order_lead_times`, `kpi.station_flow`, `kpi.downtime_reasons`, `kpi.data_quality`, `kpi.sensor_limits` and `kpi.ai_summaries`. Reporting views are `kpi.v_station_oee`, `kpi.v_station_oee_daily`, `kpi.v_downtime_pareto` and `kpi.v_alarm_log`.
