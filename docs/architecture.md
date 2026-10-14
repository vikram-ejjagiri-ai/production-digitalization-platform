# Architecture

## Design principles

1. **The simulator is replaceable.** Downstream services only see MQTT messages. Swapping the replay for a real PLC or IoT gateway (OPC UA → MQTT bridge, Node-RED, Kepware) needs no other change.
2. **Never lose the original.** Every message lands unchanged in `raw.messages` before any transformation, so data can be reprocessed when rules change.
3. **Same code for training and serving.** `common/features.py` is used by the offline trainer and the streaming detector. A unit test checks that both produce identical features.
4. **Recompute, don't accumulate.** The KPI engine recalculates the last few hours on every run, so late or out-of-order messages are handled correctly.
5. **Degrade gracefully.** No internet means synthetic data. No LLM means rule-based advice. A database restart triggers an automatic reconnect.

## Data flow

| # | Step | Component | Output |
|---|---|---|---|
| 1 | Download, clean and split by time | `pipeline/data_prep` | `data/split/part1_commissioning.csv`, `part2_live.csv`, `failures.json`, `metadata.json` |
| 2 | Commissioning analysis and training | `pipeline/training` | `models/health_model.joblib`, `machine_profile.json`, `reports/commissioning_report.html` |
| 3 | Live machine data | `simulators/sensor_replay` | MQTT `.../compressor01/sensors` (about 6 messages/s at 60×) |
| 4 | Production and RFID events | `simulators/line_simulator` | MQTT `.../stNN/events`, `.../stNN/rfid` |
| 5 | Ingestion and harmonization | `services/ingestion` | `raw.*`, `clean.sensor_readings`, `clean.line_events`, `clean.rfid_reads` |
| 6 | Streaming anomaly detection | `services/anomaly_detection` | `clean.machine_health`, `clean.alarms`, MQTT `.../compressor01/alarms` (retained) |
| 7 | KPI calculation every 30 s | `services/kpi_engine` | `kpi.*` tables |
| 8 | Recommendations and summaries | `services/ai_advisor` | `clean.ai_recommendations`, `kpi.ai_summaries` |
| 9 | Visualization | Grafana / Power BI | 3 dashboards, `kpi.v_*` views |

## MQTT topic structure (ISA-95 style)

```
factory/<plant>/<line>/<asset>/<message type>

factory/plant1/line1/compressor01/sensors        machine readings
factory/plant1/line1/compressor01/alarms         alarm state (retained)
factory/plant1/line1/compressor01/replay_status  dataset clock (retained)
factory/plant1/line1/st30/events                 production events of station 30
factory/plant1/line1/st30/rfid                   RFID reads at station 30
```

## Database layers

| Schema | Purpose | Written by | Read by |
|---|---|---|---|
| `master` | Stations, ideal cycle times, assets | init SQL | KPI engine, dashboards |
| `raw` | Messages exactly as received, plus rejected messages with the reason | ingestion | data quality KPIs, reprocessing |
| `clean` | Typed, harmonized, de-duplicated data, machine health, alarms, AI advice | ingestion, detector, advisor | KPI engine, dashboards |
| `kpi` | Aggregated KPIs and reporting views | KPI engine, advisor, detector | dashboards, Power BI |

On TimescaleDB the large tables become hypertables with retention (raw 3 days, sensor readings 14 days). The same schema also runs on plain PostgreSQL.

## Machine health model

* **Features:** for every 30-minute window (180 readings) the platform computes mean, std, min and max of the 7 analog signals, plus duty cycle (share of time loaded) and the number of load cycles. That's 30 features, recomputed every minute of machine time.
* **Detector 1, Isolation Forest:** finds unusual *combinations* of features.
* **Detector 2, max |z-score|:** finds a single feature far outside its commissioning baseline. This is the multivariate equivalent of an SPC chart.
* **Calibration:** both detectors are mapped to 0–100, where 100 is the commissioning median and 50 is the 0.5th percentile of commissioning windows. The health score is their average.
* **Alarm logic:** an alarm opens after 10 consecutive windows below 50 and closes after 10 windows above 65 (persistence plus hysteresis, so it doesn't flicker).
* **Explanation:** the 5 features furthest from baseline are stored with each health record and alarm. They feed the dashboard's "Why?" table and the AI advisor.

## AI advisor

1. **Evidence:** the alarm's top deviations, written in plain language (e.g. "duty_loaded is 7.5 standard deviations above its commissioning baseline").
2. **Context:** recent stops at ST30, the station that depends on compressed air.
3. **Retrieval:** TF-IDF search over `knowledge_base/*.md`. Feature names are translated into maintenance vocabulary first.
4. **Generation:** the LLM is instructed to answer only from the evidence and excerpts, and must return JSON with likely cause, actions, urgency, confidence and evidence.
5. **Validation:** the JSON is parsed, keys and enum values are checked, and invalid output falls back to the rule-based answer.

To scale this up, replace TF-IDF with embeddings stored in pgvector inside the same database.

## Production line model

5 stations: ST10 kitting (40 s), ST20 frame assembly (60 s), ST30 panel bonding (75 s, the bottleneck, uses compressed air), ST40 electrical installation (55 s) and ST50 final inspection (45 s). Buffers of 3 sit between stations, a CONWIP limit of 12 caps the line, stops are random (MTBF 30 min, MTTR about 3 min, five reason codes), and scrap varies by station. While a compressor alarm is open, ST30 runs 30 % slower, scraps 6× more and books additional `low_air_pressure` stops.

## Moving to a real plant

| Here | Real plant |
|---|---|
| Sensor replay | PLC → OPC UA → MQTT gateway |
| Line simulator events | MES / PLC events, or machine data acquisition |
| Simulated RFID | RFID middleware (reader events) |
| Anonymous MQTT | TLS + authentication, Sparkplug B payloads |
| Single TimescaleDB | Managed TimescaleDB / historian, backups |
| Docker Compose | Kubernetes or an industrial edge platform |
