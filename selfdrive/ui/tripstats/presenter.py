# Ported from TeslaPilot (MIT), Memberoffoxhound/TeslaPilot, branch Highland-Dev.
# https://github.com/Memberoffoxhound/TeslaPilot

"""When the trip card is due. Recording follows the UI; a Tesla in Park ends the drive on screen only."""
from __future__ import annotations

import time

from cereal import car

from openpilot.selfdrive.ui import tripstats
from openpilot.selfdrive.ui.tripstats.park_end import ParkEnd

SHOW_S = tripstats.SHOW_S
HEADLINE = "trip summary"
LAST_HEADLINE = "last trip summary"


class TripPresenter:
  def __init__(self) -> None:
    self.park = ParkEnd()
    self.drive: dict | None = None
    self.headline = HEADLINE
    self.visible = False
    self._shown_at = 0.0
    self._was_started = False
    self._was_recording = False
    self._missed_checked = False
    self._boot = time.monotonic()

  def frame(self, ui) -> None:
    now = time.monotonic()
    sample = _sample(ui)
    ended = self.park.update(
      now, tesla=sample["tesla"], gear_park=sample["gear_park"],
      engaged=sample["engaged"], speed=sample["speed"],
    )
    recording = bool(ui.started) and not ended
    just_park = ended and self._was_recording
    just_offroad = self._was_started and not ui.started
    if self.drive is None and (just_park or just_offroad) and tripstats.due_summary() is not None:
      self._begin(last=False)
    if recording and not self._was_recording:
      self.drive = None
      self.visible = False
    tripstats.tick(
      recording, now, sample["speed"] if ui.started else 0.0, sample["engaged"] if recording else False,
      sample["state"], sample["alert_status"], sample["alert_type"], sample["route"],
    )
    if not self._missed_checked and now - self._boot > 1.0 and not ui.started and self.drive is None:
      self._missed_checked = True
      if tripstats.missed_trip() is not None:
        self._begin(last=True)
    self._was_started = bool(ui.started)
    self._was_recording = recording
    if self.visible and now - self._shown_at >= SHOW_S:
      self.visible = False

  def tap(self) -> None:
    if self.visible:
      self.visible = False

  def reopen(self) -> None:
    if self.drive is not None:
      self.visible = True
      self._shown_at = time.monotonic()

  def blocks_alert(self, full_critical: bool) -> bool:
    return self.visible and self.drive is not None and not full_critical

  def _begin(self, last: bool) -> None:
    drive = tripstats.missed_trip() if last else tripstats.due_summary()
    if drive is None:
      return
    tripstats.mark_shown(drive if last else None)
    self.drive = drive
    self.headline = LAST_HEADLINE if last else HEADLINE
    self.visible = True
    self._shown_at = time.monotonic()


def _enum_name(value) -> str:
  if value is None:
    return ""
  return str(getattr(value, "name", value))


def _sample(ui) -> dict:
  sm = ui.sm
  speed = 0.0
  engaged = False
  gear_park = False
  state = alert_status = alert_type = ""
  route = ""
  brand = getattr(getattr(ui, "CP", None), "brand", "") or ""
  valid = getattr(sm, "valid", {}) or {}
  if ui.started and valid.get("carState"):
    cs = sm["carState"]
    speed = max(0.0, float(getattr(cs, "vEgo", 0.0)))
    gear_park = getattr(cs, "gearShifter", None) == car.CarState.GearShifter.park
  if ui.started and valid.get("selfdriveState"):
    ss = sm["selfdriveState"]
    engaged = bool(getattr(ss, "enabled", False))
    state = _enum_name(getattr(ss, "state", ""))
    alert_status = _enum_name(getattr(ss, "alertStatus", "normal"))
    alert_type = str(getattr(ss, "alertType", "") or "")
  try:
    raw = ui.params.get("CurrentRoute", encoding="utf-8") or ""
  except Exception:
    raw = ""
  route = raw if isinstance(raw, str) else ""
  return {
    "tesla": brand == "tesla", "gear_park": gear_park, "engaged": engaged, "speed": speed,
    "state": state, "alert_status": alert_status, "alert_type": alert_type, "route": route,
  }


presenter = TripPresenter()
