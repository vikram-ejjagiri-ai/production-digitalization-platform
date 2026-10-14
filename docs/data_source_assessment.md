# Data source assessment

Before building KPIs, each data source was assessed for availability, quality and fitness for purpose, the same way you'd assess sources in a brownfield plant.

| Source | Content | Frequency | Format issues found | Handling | Fit for |
|---|---|---|---|---|---|
| Compressor sensors (MetroPT-3) | 7 analog + 8 digital signals | About every 10 s | Unlabeled; recording gaps; column typo `DV_eletric`; mixed analog/digital | Renamed and typed; gaps measured in the data prep report and compressed during replay; failure reports used **only for evaluation** | Condition monitoring, anomaly detection |
| Station events ST10/ST20 ("legacy PLCs") | Cycle, stop, order events | Per event | Epoch-millisecond timestamps, durations in **ms**, IDs `ST10` / `st-20` | Converted to UTC timestamps and seconds; IDs mapped to master data | OEE, MTBF/MTTR, downtime Pareto |
| Station events ST30–ST50 | Same | Per event | ISO timestamps, durations in **s**, IDs `Station_30`, `STATION 40`, `st50` | Same canonical format | Same |
| RFID readers (IN/OUT per station) | Tag EPC, reader, RSSI | Per pass | About 15 % **duplicate reads** within 0.2–1.5 s; station encoded in reader name | De-duplicated within 3 s per tag/reader/direction; station parsed from the reader name | Lead time, WIP, dwell and wait times, bottleneck analysis |
| Master data | Stations, ideal cycle times, asset → station link | Static | – | Kept in `master` schema | KPI targets, linking machine health to production |
| Maintenance knowledge | FMEA, SOPs | Static | Unstructured text | Split into sections and indexed for retrieval | AI recommendations |

## Quality rules applied in ingestion

1. The payload must be valid JSON and a JSON object. Otherwise it's rejected with a reason.
2. The station ID must map to master data. Unknown stations are rejected.
3. The event type must be one of the six known types.
4. Durations must be non-negative.
5. EPCs must be 16–32 hex characters.
6. Sensor values outside their physically plausible range are **flagged, not dropped**, because a broken sensor is itself information.
7. Raw messages are always stored, so nothing is lost when a rule is wrong.

The results are visible in the **Data quality** panel of the management dashboard (`kpi.data_quality`).

## Gaps and recommendations

* **No shift calendar.** Planned time currently assumes 24/7 operation. Add breaks and planned maintenance to `master` for accurate availability.
* **No operator confirmation of stop reasons.** In a real plant, reason codes are often missing or wrong. A short operator dialogue at the station would raise the quality of the downtime Pareto.
* **Compressor data has no maintenance log** apart from the four reported failures. Logging work orders would allow supervised models and remaining useful life (RUL) estimation.
* **RFID coverage.** Only station IN/OUT readers exist. Adding buffer and warehouse readers would make WIP and waiting time more precise.
