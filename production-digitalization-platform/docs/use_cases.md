# Data-driven use cases

Each feature is framed as a use case with a business question, a solution and a way to measure success, as you'd present it to a department before a rollout.

## UC1: Predictive maintenance for the compressed-air supply
* **Problem:** air leaks in the compressor circuit are only noticed when production stations lose pressure.
* **Solution:** the health model learns normal behaviour during commissioning and raises an alarm on deviation. Root-cause hints come from the top deviating features, and the AI advisor turns them into actions from the FMEA.
* **Measured by:** failures detected, early-warning lead time (hours before the reported failure), false alarms per week. All three are in `reports/model_evaluation.json`.
* **Value:** maintenance can be planned before the failure. A leak also wastes energy, since the compressor runs longer under load (visible as a duty cycle increase).

## UC2: Linking machine health to production losses
* **Problem:** maintenance and production look at separate systems.
* **Solution:** ST30 (panel bonding) is linked to the compressor in master data. During an alarm, the dashboards show ST30 OEE dropping, `low_air_pressure` stops and higher scrap side by side with the compressor health.
* **Measured by:** OEE loss at ST30 during alarm windows vs. normal operation.
* **Value:** maintenance is prioritized by its impact on output, not just by machine condition.

## UC3: Harmonized OEE across heterogeneous stations
* **Problem:** stations from different vendors report in different formats, so KPIs aren't comparable.
* **Solution:** one harmonization layer and one documented KPI definition (`kpi_definitions.md`).
* **Measured by:** 0 rejected messages and identical KPI logic for all stations.
* **Value:** one trusted number per KPI for shopfloor and management.

## UC4: RFID-based lead time and bottleneck analysis
* **Problem:** where do parts wait, and how long does an order really take?
* **Solution:** RFID IN/OUT reads per station give lead time, value-adding time, waiting time, flow efficiency and waiting time in front of each station.
* **Measured by:** flow efficiency trend, and wait time before the bottleneck.
* **Value:** WIP and lead time reduction. It also shows that ST30 is the constraint where improvement pays off first (theory of constraints).

## UC5: Downtime Pareto for continuous improvement
* **Problem:** which losses should we work on first?
* **Solution:** stop reasons aggregated per station and reason.
* **Measured by:** downtime minutes of the top reason, week over week.
* **Value:** focused improvement work (e.g. kitting / logistics for `material_missing`).

## UC6: Automated shift summary
* **Problem:** shift handovers take time and depend on who's writing.
* **Solution:** every 15 minutes the AI advisor writes a short summary from the KPIs, the downtime Pareto and the alarms. The LLM only uses the numbers it is given, and a rule-based fallback is available.
* **Value:** a consistent, quick handover. The KPI numbers stay the source of truth.
