# Display-only drive end for a Tesla that stays onroad in Park.
# This does not change hardwared, the manager, panda safety, or whether the device is onroad.
# TeslaPilot's "go offroad in park" process is not ported.

"""Hold Park, stopped and not engaged, before a Tesla drive counts as ended."""
from __future__ import annotations

from openpilot.selfdrive.ui.tripstats.recorder import MOVING_V

PARK_HOLD_S = 3.0


class ParkEnd:
  def __init__(self) -> None:
    self._since: float | None = None
    self.ended = False

  def update(self, now: float, *, tesla: bool, gear_park: bool, engaged: bool, speed: float) -> bool:
    holding = tesla and gear_park and not engaged and speed <= MOVING_V
    if not holding:
      self._since = None
      self.ended = False
      return False
    if self._since is None:
      self._since = now
    if now - self._since >= PARK_HOLD_S:
      self.ended = True
    return self.ended
