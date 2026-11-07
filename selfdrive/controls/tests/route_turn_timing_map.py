"""Offline route-intent timing map.

Reads the current desire, turn-lead, navigation-speed, and Tesla lateral-accel
constants. Nothing here is imported by controlsd, DesireHelper, or
LaneCenteringController. It does not publish, enable nav longitudinal control,
or complete a turn. A desire flag is model intent input only.

Taking the wheel on a wide turn is an intervention, not a successful turn.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from openpilot.common.constants import CV
from openpilot.selfdrive.controls.lib.desire_helper import (
  NAV_TURN_MAX_DISTANCE,
  NAV_TURN_MAX_SPEED,
  NAV_TURN_MIN_DISTANCE,
  NAV_TURN_PREVIEW_SECONDS,
  NAV_TURN_SIGNAL_BASE_DISTANCE,
  NAV_TURN_SIGNAL_LEAD_TIME,
  NAV_TURN_SIGNAL_MAX_DISTANCE,
  NAV_TURN_SIGNAL_MIN_DISTANCE,
)
from openpilot.selfdrive.controls.tests.wide_turn_stage_harness import (
  controlsd_constant,
  left_arc,
  tesla_min_radius_m,
  turn_lead_would_be_active,
)


_REPO = Path(__file__).resolve().parents[3]

# Same synthetic left arc the wide-turn stage harness builds with left_arc(20).
SYNTHETIC_LEFT_ARC_RADIUS_M = 20.0

DEFAULT_APPROACH_SPEEDS_M_S = (3.0, 5.0, 7.0, 8.0, 10.0, 12.0, 13.9, 14.0)


def _read(relative: str) -> str:
  return (_REPO / relative).read_text(encoding="utf-8")


def preview_distance_m(speed_m_s: float) -> float:
  """DesireHelper._nav_turn_is_imminent preview window."""
  return float(np.clip(
    max(float(speed_m_s), 0.0) * NAV_TURN_PREVIEW_SECONDS,
    NAV_TURN_MIN_DISTANCE,
    NAV_TURN_MAX_DISTANCE,
  ))


def signal_lead_distance_m(speed_m_s: float) -> float:
  """DesireHelper._nav_turn_signal_matches lane-change suppression distance."""
  return float(np.clip(
    NAV_TURN_SIGNAL_BASE_DISTANCE + max(float(speed_m_s), 0.0) * NAV_TURN_SIGNAL_LEAD_TIME,
    NAV_TURN_SIGNAL_MIN_DISTANCE,
    NAV_TURN_SIGNAL_MAX_DISTANCE,
  ))


def route_turn_desire_possible(speed_m_s: float) -> bool:
  """Speed gate only. Other route-turn gates are assumed satisfied."""
  return 0.0 <= float(speed_m_s) < NAV_TURN_MAX_SPEED


def nav_turn_table_mph() -> dict[str, float]:
  """Literal mph factors in NAV_TURN_TARGET_SPEEDS. Does not import vcruise."""
  text = _read("starpilot/controls/lib/starpilot_vcruise.py")
  match = re.search(r"NAV_TURN_TARGET_SPEEDS = \{(?P<body>.*?)\n\}", text, re.S)
  if match is None:
    raise RuntimeError("NAV_TURN_TARGET_SPEEDS not found")
  found = re.findall(r'"(\w+)": ([0-9.]+) \* CV\.MPH_TO_MS', match.group("body"))
  if not found:
    raise RuntimeError("NAV_TURN_TARGET_SPEEDS has no mph entries")
  return {name: float(mph) for name, mph in found}


def nav_longitudinal_allowed_required() -> bool:
  """True when the cruise target stays off unless the toggle is already set."""
  text = _read("starpilot/controls/lib/starpilot_vcruise.py")
  start = text.find("def _get_nav_turn_control_target")
  lookup = text.find("def _nav_maneuver_target_speed")
  if start < 0 or lookup < 0:
    return False
  gate = text[start:start + 600]
  table = text[lookup:lookup + 700]
  return (
    'if not getattr(starpilot_toggles, "nav_longitudinal_allowed", False):' in gate
    and "return 0.0" in gate
    and 'if maneuver_type == "turn":' in table
    and "return NAV_TURN_TARGET_SPEEDS.get(maneuver_modifier)" in table
  )


def _checked_arc_radius_m(radius_m: float) -> float:
  xs, ys = left_arc(radius_m)
  recovered = np.hypot(np.asarray(xs, dtype=float), np.asarray(ys, dtype=float) + radius_m)
  if recovered.size == 0 or not np.allclose(recovered, radius_m, rtol=0.0, atol=1e-6):
    raise RuntimeError("left_arc is not the synthetic constant-radius left turn")
  return float(radius_m)


@dataclass(frozen=True)
class RouteTurnTimingRow:
  speed_m_s: float
  preview_distance_m: float
  signal_lead_distance_m: float
  desire_possible: bool
  turn_lead_active: bool
  desire_without_turn_lead: bool
  nav_left_target_mph: float
  nav_right_target_mph: float
  nav_left_target_m_s: float
  nav_right_target_m_s: float
  nav_longitudinal_allowed_required: bool
  arc_radius_m: float
  tesla_min_radius_m: float
  tesla_cap_widens_arc: bool


@dataclass(frozen=True)
class RouteTurnTimingMap:
  rows: tuple[RouteTurnTimingRow, ...]
  arc_radius_m: float
  nav_turn_max_speed_m_s: float
  turn_lead_min_m_s: float
  turn_lead_max_m_s: float

  def row_at(self, speed_m_s: float) -> RouteTurnTimingRow:
    for row in self.rows:
      if abs(row.speed_m_s - speed_m_s) < 1e-9:
        return row
    raise KeyError(speed_m_s)


def build_timing_map(
  speeds_m_s: tuple[float, ...] = DEFAULT_APPROACH_SPEEDS_M_S,
  arc_radius_m: float = SYNTHETIC_LEFT_ARC_RADIUS_M,
) -> RouteTurnTimingMap:
  if not nav_longitudinal_allowed_required():
    raise RuntimeError("nav longitudinal target gate was not found; not reporting it as active")

  table = nav_turn_table_mph()
  left_mph = table["left"]
  right_mph = table["right"]
  arc = _checked_arc_radius_m(arc_radius_m)
  lead_min = controlsd_constant("TURN_LEAD_MIN_SPEED")
  lead_max = controlsd_constant("TURN_LEAD_MAX_SPEED")

  rows = []
  for speed in speeds_m_s:
    desire = route_turn_desire_possible(speed)
    lead = turn_lead_would_be_active(speed)
    min_radius = tesla_min_radius_m(speed)
    rows.append(RouteTurnTimingRow(
      speed_m_s=float(speed),
      preview_distance_m=preview_distance_m(speed),
      signal_lead_distance_m=signal_lead_distance_m(speed),
      desire_possible=desire,
      turn_lead_active=lead,
      desire_without_turn_lead=desire and not lead,
      nav_left_target_mph=left_mph,
      nav_right_target_mph=right_mph,
      nav_left_target_m_s=left_mph * CV.MPH_TO_MS,
      nav_right_target_m_s=right_mph * CV.MPH_TO_MS,
      nav_longitudinal_allowed_required=True,
      arc_radius_m=arc,
      tesla_min_radius_m=min_radius,
      tesla_cap_widens_arc=min_radius > arc,
    ))
  return RouteTurnTimingMap(
    rows=tuple(rows),
    arc_radius_m=arc,
    nav_turn_max_speed_m_s=float(NAV_TURN_MAX_SPEED),
    turn_lead_min_m_s=lead_min,
    turn_lead_max_m_s=lead_max,
  )


def format_timing_map(report: RouteTurnTimingMap | None = None) -> str:
  report = build_timing_map() if report is None else report
  header = (
    "speed  preview  signal  desire  lead  gap  tesla_r  widens  "
    f"nav_left {report.rows[0].nav_left_target_mph:.0f} mph "
    f"nav_right {report.rows[0].nav_right_target_mph:.0f} mph "
    f"nav_long_required {report.rows[0].nav_longitudinal_allowed_required} "
    f"arc {report.arc_radius_m:.0f} m"
  )
  lines = [header]
  for row in report.rows:
    lines.append(
      f"{row.speed_m_s:5.1f}  {row.preview_distance_m:7.1f}  {row.signal_lead_distance_m:6.1f}  "
      f"{str(row.desire_possible):5}  {str(row.turn_lead_active):5}  "
      f"{str(row.desire_without_turn_lead):5}  {row.tesla_min_radius_m:7.2f}  "
      f"{str(row.tesla_cap_widens_arc):5}"
    )
  return "\n".join(lines)


if __name__ == "__main__":
  print(format_timing_map())
