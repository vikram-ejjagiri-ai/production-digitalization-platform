# Line 1 – Standard operating procedures

## SOP-ST30 Panel bonding station and compressed air supply
Station ST30 (panel bonding) presses adhesive-bonded panels with pneumatic cylinders supplied by compressor01. Minimum supply pressure is 6 bar. When the compressor health alarm is active or the station reports low_air_pressure stops: 1) Inform the maintenance shift lead. 2) Switch ST30 to the backup air connection if available. 3) Mark all panels bonded during the alarm window for extra bond-strength inspection at ST50. 4) If stops repeat, reduce the release rate at ST10 to avoid building WIP in front of ST30, the line bottleneck.

## SOP-DT Downtime reason handling
Operators must book every stop with a reason code: material_missing, tool_change, machine_fault, quality_check, operator_absent, low_air_pressure. Material_missing stops above 10 % of planned time indicate a kitting or logistics problem and should be escalated to logistics. Repeated machine_fault on the same station within a shift triggers a maintenance work order.

## SOP-KPI Shift review
At each shift handover review: OEE per station (target 75 %), first pass yield (target 97 %), top three downtime reasons (Pareto), lead time trend from RFID, and open machine alarms with their recommended actions.
