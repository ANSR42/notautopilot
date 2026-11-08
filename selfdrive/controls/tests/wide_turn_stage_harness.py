"""Offline stage report for a synthetic wide-turn diagnosis.

Nothing here is imported by controlsd, DesireHelper, or LaneCenteringController.
The numbers are the current production functions and constants. They are not a
completed turn and not a log replay.
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from openpilot.selfdrive.controls.lib.lane_centering import LaneCenteringController
from opendbc.car.tesla.values import CarControllerParams


_REPO = Path(__file__).resolve().parents[3]


def _read(relative: str) -> str:
  return (_REPO / relative).read_text(encoding="utf-8")


def controlsd_constant(name: str) -> float:
  match = re.search(rf"^{name} = ([0-9.]+)", _read("selfdrive/controls/controlsd.py"), re.M)
  if match is None:
    raise RuntimeError(f"missing {name} in controlsd.py")
  return float(match.group(1))


def circle_curvature_1_per_m(xs, ys, lookahead_m: float) -> float:
  """Same chord fit as controlsd._plan_circle_curvature. Positive is to the right."""
  px, py = 0.0, 0.0
  for x, y in zip(xs, ys, strict=False):
    x, y = float(x), float(y)
    if not (math.isfinite(x) and math.isfinite(y)):
      return 0.0
    px, py = x, y
    if math.hypot(x, y) >= lookahead_m:
      break
  d2 = px * px + py * py
  if d2 < 1.0:
    return 0.0
  return 2.0 * py / d2


def left_arc(radius_m: float, n: int = 80):
  """Plan points on a left turn. y is negative, so the fitted curvature is negative."""
  thetas = np.linspace(0.0, 1.2, n)
  xs = radius_m * np.sin(thetas)
  ys = -radius_m * (1.0 - np.cos(thetas))
  return xs, ys


def tesla_max_abs_curvature_1_per_m(speed_m_s: float) -> float:
  speed = max(float(speed_m_s), 1.0)
  return float(CarControllerParams.ANGLE_LIMITS.MAX_LATERAL_ACCEL) / speed ** 2


def tesla_min_radius_m(speed_m_s: float) -> float:
  return 1.0 / tesla_max_abs_curvature_1_per_m(speed_m_s)


def turn_lead_would_be_active(speed_m_s: float) -> bool:
  low = controlsd_constant("TURN_LEAD_MIN_SPEED")
  high = controlsd_constant("TURN_LEAD_MAX_SPEED")
  return low <= float(speed_m_s) < high


@dataclass(frozen=True)
class WideTurnStages:
  speed_m_s: float
  model_curvature_1_per_m: float
  lane_centering_before_pause_1_per_m: float
  lane_centering_after_pause_1_per_m: float
  turn_lead_active: bool
  turn_lead_min_m_s: float
  turn_lead_max_m_s: float
  requested_curvature_1_per_m: float
  requested_curvature_without_pause_1_per_m: float
  tesla_max_abs_curvature_1_per_m: float
  tesla_min_radius_m: float
  model_radius_m: float
  requested_radius_m: float
  tesla_limited_radius_m: float

  @property
  def lane_centering_opposes_model(self) -> bool:
    correction = self.lane_centering_before_pause_1_per_m
    return correction * self.model_curvature_1_per_m < 0.0

  @property
  def tesla_cap_widens_radius(self) -> bool:
    return abs(self.requested_curvature_1_per_m) > self.tesla_max_abs_curvature_1_per_m + 1e-9


def _settle(model, speed_m_s: float, pause: bool, blinker: bool) -> float:
  controller = LaneCenteringController()
  output = 0.0
  for _ in range(400):
    output = controller.update(0.0, model, speed_m_s, True, 0.0, 0.0, True, True, pause, blinker, False)
  return float(output)


def _lane_model(xs, ys):
  from types import SimpleNamespace

  from cereal import log

  line_x = np.linspace(0.0, 50.0, 52)
  def line(y):
    return SimpleNamespace(x=line_x.copy(), y=np.full_like(line_x, float(y)), yStd=np.full_like(line_x, 0.05))

  return SimpleNamespace(
    laneLines=[line(0.0), line(-1.8), line(1.8), line(0.0)],
    laneLineProbs=[0.0, 0.95, 0.95, 0.0],
    laneLineStds=[0.0, 0.05, 0.05, 0.0],
    position=SimpleNamespace(x=np.asarray(xs, dtype=float), y=np.asarray(ys, dtype=float), yStd=np.full(len(xs), 0.05)),
    meta=SimpleNamespace(laneChangeState=log.LaneChangeState.off),
  )


def diagnose(speed_m_s: float, radius_m: float = 20.0, blinker: bool = True) -> WideTurnStages:
  """Report one synthetic left arc. blinker selects the pause-on-signal correction."""
  xs, ys = left_arc(radius_m)
  lookahead = float(np.clip(speed_m_s, 8.0, 35.0))
  model_curvature = circle_curvature_1_per_m(xs, ys, lookahead)
  model = _lane_model(xs, ys)
  before = _settle(model, speed_m_s, pause=False, blinker=False)
  after = _settle(model, speed_m_s, pause=True, blinker=True)
  # The controller returns model_curvature + correction, and the model curvature
  # argument above is 0, so the return value is the additive correction.
  correction_before = before
  correction_after = after
  used = correction_after if blinker else correction_before
  requested = model_curvature + used
  requested_without_pause = model_curvature + correction_before
  cap = tesla_max_abs_curvature_1_per_m(speed_m_s)
  limited = math.copysign(min(abs(requested), cap), requested) if requested != 0.0 else 0.0
  return WideTurnStages(
    speed_m_s=float(speed_m_s),
    model_curvature_1_per_m=float(model_curvature),
    lane_centering_before_pause_1_per_m=float(correction_before),
    lane_centering_after_pause_1_per_m=float(correction_after),
    turn_lead_active=turn_lead_would_be_active(speed_m_s),
    turn_lead_min_m_s=controlsd_constant("TURN_LEAD_MIN_SPEED"),
    turn_lead_max_m_s=controlsd_constant("TURN_LEAD_MAX_SPEED"),
    requested_curvature_1_per_m=float(requested),
    requested_curvature_without_pause_1_per_m=float(requested_without_pause),
    tesla_max_abs_curvature_1_per_m=float(cap),
    tesla_min_radius_m=float(tesla_min_radius_m(speed_m_s)),
    model_radius_m=float(1.0 / abs(model_curvature)),
    requested_radius_m=float(1.0 / abs(requested)) if requested != 0.0 else math.inf,
    tesla_limited_radius_m=float(1.0 / abs(limited)) if limited != 0.0 else math.inf,
  )
