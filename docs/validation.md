# Validation

How the results were checked, and how a process engineer could review them.

## 1. Unit tests (`pytest`, 20 tests)

| Area | What is checked |
|---|---|
| Harmonization | Every station ID format maps to the right canonical ID; ms → s conversion; epoch-ms → UTC; unknown stations and event types are rejected; RFID duplicate window; out-of-range sensor values are flagged, not dropped |
| KPIs | Textbook OEE example (A = 50/60, P = 0.8, Q = 0.95), open stops counted until now, MTTR, lead time / value-adding / waiting time and wait-before-station from RFID |
| Model | Streaming and batch features are identical (no training/serving skew); health drops below 50 for abnormal data; alarm persistence and hysteresis |
| Advisor | An air-leak signature retrieves the air-leak FMEA entry; the rule-based fallback returns actions; invalid LLM output is corrected |

## 2. Model evaluation against maintenance records

The anomaly model never sees the failure reports during training. After training, the reports are used to evaluate the model on Part 2: detected yes/no, lead time, and false alarms per week. Results are written to `reports/model_evaluation.json` and the commissioning report. An alarm counts as a detection if it opens up to 48 h before or during a reported failure.

## 3. End-to-end integration run

All services were run together against PostgreSQL and an MQTT broker, with the replay at 600× and the line at 10×. Results:
* the alarm opened about 2.5 h (dataset time) before the first reported failure, and closed shortly after the failure window ended
* ST30 switched to degraded mode on the retained alarm message and booked `low_air_pressure` stops
* KPI tables, lead times, flow and data quality were filled with 0 rejected messages
* the AI advisor produced a recommendation and a shift summary, both through the LLM path and through the rule-based fallback
* every SQL query in the three dashboards was executed against the populated database without errors

## 4. Plausibility checks a process engineer would do

| Check | Expected |
|---|---|
| ST30 has the lowest performance-limited throughput | It's the bottleneck (75 s ideal cycle) |
| Wait time before ST30 > wait before other stations | Queue in front of the bottleneck |
| Sum of good + scrap at ST50 + scrap upstream = completed orders | Mass balance holds |
| OEE ≤ min(A, P, Q) | Always |
| Health score ≈ 100 most of the time in healthy periods | Calibrated on commissioning data |
| `rfid_duplicates` ≈ 15 % of RFID messages | Matches the reader behaviour |

To check the numbers by hand, run the SQL in the dashboard panels directly in any SQL client. Use the `bi_reader` login, which is read-only.
