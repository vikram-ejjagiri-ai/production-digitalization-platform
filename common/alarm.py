"""Alarm state machine with persistence and hysteresis.

An alarm opens only after `open_after` consecutive bad windows and closes only
after `close_after` consecutive good windows. This stops alarm "flickering",
which operators quickly learn to ignore.
"""
from dataclasses import dataclass

ALARM_BELOW = 50.0  # health score that counts as "bad"
WARNING_BELOW = 70.0
CLEAR_ABOVE = 65.0  # must recover above this to count as "good" (hysteresis)


@dataclass
class AlarmTracker:
    open_after: int
    close_after: int
    active: bool = False
    bad_count: int = 0
    good_count: int = 0

    def update(self, health: float) -> str | None:
        """Feed one health score. Returns 'open', 'close' or None (no state change)."""
        if health < ALARM_BELOW:
            self.bad_count += 1
            self.good_count = 0
        elif health > CLEAR_ABOVE:
            self.good_count += 1
            self.bad_count = 0
        if not self.active and self.bad_count >= self.open_after:
            self.active = True
            return "open"
        if self.active and self.good_count >= self.close_after:
            self.active = False
            return "close"
        return None


def status_of(health: float, alarm_active: bool) -> str:
    if alarm_active:
        return "alarm"
    if health < WARNING_BELOW:
        return "warning"
    return "normal"
