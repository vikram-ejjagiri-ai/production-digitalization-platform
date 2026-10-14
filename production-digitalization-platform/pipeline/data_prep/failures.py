"""Failure reports published with the MetroPT-3 dataset (UCI, CC BY 4.0).

The raw data is unlabeled; these maintenance reports are used only to EVALUATE
the anomaly detector, never to train it (that is what a real plant would have).
"""
FAILURES = [
    {"id": 1, "type": "Air leak", "start": "2020-04-18 00:00", "end": "2020-04-18 23:59"},
    {"id": 2, "type": "Air leak", "start": "2020-05-29 23:30", "end": "2020-05-30 06:00"},
    {"id": 3, "type": "Air leak", "start": "2020-06-05 10:00", "end": "2020-06-07 14:30"},
    {"id": 4, "type": "Air leak", "start": "2020-07-15 14:30", "end": "2020-07-15 19:00"},
]
