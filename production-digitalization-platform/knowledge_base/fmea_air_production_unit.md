# FMEA – Air Production Unit (compressor01)

Maintenance knowledge base used by the AI advisor (retrieval-augmented generation).
Each section is one failure mode. Edit or extend this file to teach the advisor
about your own equipment – no code changes needed.

## FM-01 Air leak in the pneumatic circuit
Symptoms: compressor duty cycle (share of time loaded) clearly above baseline; more frequent load cycles; reservoir pressure drops faster while the compressor is off; longer loaded phases; motor current and oil temperature drift upward because the compressor runs more; LPS (low pressure switch) may activate when the leak is large.
Likely causes: leaking fittings, hoses or quick couplings; damaged reservoir seals; drain valve stuck open; leaking pneumatic consumer (e.g. bonding press cylinder).
Recommended actions: 1) Run a pressure-decay test with the compressor stopped and compare with the baseline decay rate. 2) Locate the leak with an ultrasonic leak detector or soapy water at fittings, couplings and drain valves. 3) Check the condensate drain valves for sticking. 4) Inspect consumers on the line that use compressed air (panel bonding station ST30). 5) Plan the repair for the next planned stop; repair immediately if LPS activates.
Urgency: high – leaks waste energy, overheat the compressor and can starve production of air.
Production impact: stations that use compressed air (ST30 panel bonding) run slower and produce more scrap when pressure is unstable.

## FM-02 Oil leak or low oil level
Symptoms: oil level signal active; oil temperature above baseline at similar load; motor current slightly higher; visible oil around the compressor housing.
Likely causes: worn shaft seal; loose oil drain plug; damaged oil cooler hose.
Recommended actions: 1) Check the oil level sight glass and top up with the specified oil. 2) Inspect seals, drain plug and cooler hoses for leaks. 3) Check the oil separator element. 4) Do not run the compressor with low oil – risk of seizure.
Urgency: high.
Production impact: unplanned compressor stop takes air supply away from ST30.

## FM-03 Clogged intake filter or oil separator
Symptoms: compressor outlet pressure (TP2) high relative to panel pressure (TP3); abnormal H1 pressure (cyclonic separator filter discharge); higher motor current under load; slower pressure build-up.
Likely causes: dirty intake air filter; saturated oil separator element; blocked cyclonic separator drain.
Recommended actions: 1) Check differential pressure across the intake filter and separator. 2) Replace the intake filter / separator element if above limit. 3) Clean the cyclonic separator drain.
Urgency: medium.
Production impact: reduced air capacity during peak demand.

## FM-04 Air dryer tower or purge valve fault
Symptoms: abnormal DV pressure peaks (tower discharge); towers signal not alternating as usual; pressure switch irregular; moisture in the air lines.
Likely causes: stuck purge valve; failed tower switching solenoid; saturated desiccant.
Recommended actions: 1) Verify tower switching sequence. 2) Test the purge/discharge solenoid valves. 3) Check dew point; replace desiccant if saturated.
Urgency: medium.
Production impact: wet air can cause bonding defects at ST30 – inspect parts bonded during the fault.

## FM-05 Compressor overheating / cooling problem
Symptoms: oil temperature well above baseline even at normal duty cycle; temperature keeps rising during long loaded phases.
Likely causes: blocked oil cooler fins; failed cooling fan; high ambient temperature; thermostatic valve stuck.
Recommended actions: 1) Clean the oil cooler. 2) Check the cooling fan and its motor. 3) Check the thermostatic valve. 4) Check ventilation of the compressor room.
Urgency: high if temperature approaches the trip limit.
Production impact: thermal trip stops the compressor.

## FM-06 Motor or electrical problem
Symptoms: motor current spikes or unusual starting current; frequent motor starts; current high while pressure behaviour is normal.
Likely causes: worn bearings; phase imbalance; loose terminals; contactor wear.
Recommended actions: 1) Measure current on all three phases. 2) Check terminals and contactor. 3) Check bearings with vibration measurement.
Urgency: medium.
Production impact: risk of unplanned motor failure.

## FM-07 Pressure sensor drift or failure
Symptoms: one pressure signal deviates while the other pressure signals and motor current look normal; values physically implausible.
Likely causes: sensor drift; damaged cable; loose connector.
Recommended actions: 1) Compare the sensor with a calibrated reference gauge. 2) Check wiring. 3) Recalibrate or replace the sensor. Do not act on process changes until the sensor is confirmed.
Urgency: low to medium.
Production impact: false alarms or missed alarms in monitoring.
