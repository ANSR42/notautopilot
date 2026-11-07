"""Offline angle-space stages for a synthetic Tesla wide turn.

Nothing here is imported by controlsd, DesireHelper, LaneCenteringController,
or CarController. The numbers call the current production functions. They are
synthetic investigative stages, not a completed turn, not a log replay, and
not proof of Mike's intervention cause.
"""

from dataclasses import dataclass
from functools import lru_cache
import math

import numpy as np

from opendbc.car import DT_CTRL, rate_limit
from opendbc.car.lateral import apply_steer_angle_limits_vm, get_max_angle_delta_vm, get_max_angle_vm
from opendbc.car.tesla.carcontroller import get_safety_CP
from opendbc.car.tesla.values import CAR, CarControllerParams
from opendbc.car.vehicle_model import VehicleModel
from openpilot.selfdrive.controls.tests.wide_turn_stage_harness import diagnose


INVESTIGATION_LABEL = "synthetic investigative stages; not a completed turn; not a log replay; not proof of Mike's intervention cause"

# One name per step. The rate cap does not get a second name when it only ties the jerk delta.
BINDER_JERK_DELTA = "jerk_delta"
BINDER_MAX_ANGLE_RATE = "max_angle_rate"
BINDER_ACCEL_MAX_ANGLE = "accel_max_angle"
BINDER_NONE = "none"
BINDER_NAMES = frozenset(
  {
    BINDER_JERK_DELTA,
    BINDER_MAX_ANGLE_RATE,
    BINDER_ACCEL_MAX_ANGLE,
    BINDER_NONE,
  }
)

ARC_RADIUS_M = 20.0
SPEEDS_M_S = (5.0, 7.0, 8.0, 10.0, 13.9)
# CarController sends the angle every STEER_STEP control frames (50 Hz).
DEFAULT_FRAMES = 250
_BIND_EPS = 1e-9


def command_dt_s() -> float:
  """Seconds between apply_steer_angle_limits_vm calls in CarController.update."""
  return float(DT_CTRL * CarControllerParams.STEER_STEP)


@lru_cache(maxsize=1)
def model_y_vehicle_model() -> VehicleModel:
  """Same model CarController builds for HW3/HW4 Tesla angle limits.

  get_safety_CP() is CarInterface.get_non_essential_params(CAR.TESLA_MODEL_Y).
  Cooperative steering is not part of that model and is not active for Model Y.
  """
  return VehicleModel(get_safety_CP())


def model_y_uses_cooperative_steering() -> bool:
  """CarController.coop_enabled requires TESLA_MODEL_3 and the safety flag."""
  return False


def latcontrol_angle_desired_deg(desired_curvature: float, speed_m_s: float, vm: VehicleModel, roll: float = 0.0, angle_offset_deg: float = 0.0) -> float:
  """LatControlAngle.update while active, with the Tesla sign flip and no ascent terms.

  use_steer_limited_by_safety is true for brand tesla, so this angle is not clipped here.
  """
  steer_rad = vm.get_steer_from_curvature(-float(desired_curvature), float(speed_m_s), float(roll))
  return math.degrees(steer_rad) + float(angle_offset_deg)


def tighter_delta_binder(jerk_delta_deg: float, max_angle_rate_deg: float) -> str:
  """Which delta source survives min(jerk delta, MAX_ANGLE_RATE).

  A tie keeps the jerk name: the rate cap does not reduce the jerk delta.
  """
  if float(jerk_delta_deg) <= float(max_angle_rate_deg):
    return BINDER_JERK_DELTA
  return BINDER_MAX_ANGLE_RATE


def classify_first_binder(apply_angle: float, apply_angle_last: float, v_ego_raw: float, vm: VehicleModel) -> tuple[str, bool, float]:
  """First constraint that changes the command, then whether the accel clip also changes it.

  Order matches apply_steer_angle_limits_vm with lat_active true:
  jerk delta, capped by MAX_ANGLE_RATE, then the accel max angle, then STEER_ANGLE_MAX.
  The inactive branch is not used. STEER_ANGLE_MAX is not a named binder; a command
  that first hits it is rejected instead of being mislabeled.
  """
  limited = apply_steer_angle_limits_vm(
    apply_angle,
    apply_angle_last,
    v_ego_raw,
    0.0,
    True,
    CarControllerParams,
    vm,
  )
  v_ego = max(float(v_ego_raw), 1.0)
  jerk_delta = get_max_angle_delta_vm(v_ego, vm, CarControllerParams)
  rate_cap = float(CarControllerParams.ANGLE_LIMITS.MAX_ANGLE_RATE)
  delta = min(jerk_delta, rate_cap)
  after_rate = rate_limit(apply_angle, apply_angle_last, -delta, delta)
  max_angle = get_max_angle_vm(v_ego, vm, CarControllerParams)
  after_accel = float(np.clip(after_rate, -max_angle, max_angle))
  steer_max = float(CarControllerParams.ANGLE_LIMITS.STEER_ANGLE_MAX)
  after_fault = float(np.clip(after_accel, -steer_max, steer_max))
  if abs(after_fault - limited) > 1e-6:
    raise RuntimeError("angle reconstruction diverged from apply_steer_angle_limits_vm")
  if abs(after_fault - after_accel) > _BIND_EPS:
    raise RuntimeError("STEER_ANGLE_MAX bound the command and is not a named binder")

  rate_binds = abs(after_rate - apply_angle) > _BIND_EPS
  accel_binds = abs(after_accel - after_rate) > _BIND_EPS
  if rate_binds:
    return tighter_delta_binder(jerk_delta, rate_cap), accel_binds, float(limited)
  if accel_binds:
    return BINDER_ACCEL_MAX_ANGLE, True, float(limited)
  return BINDER_NONE, False, float(limited)


@dataclass(frozen=True)
class AngleLimitStep:
  frame: int
  time_s: float
  angle_deg: float
  first_binder: str
  accel_clip_applied: bool


@dataclass(frozen=True)
class TeslaSteerResponse:
  label: str
  speed_m_s: float
  radius_m: float
  blinker: bool
  cooperative_steering_active: bool
  roll_rad: float
  angle_offset_deg: float
  spec_mass_kg: float
  vehicle_model_mass_kg: float
  wheelbase_m: float
  steer_ratio: float
  model_curvature_1_per_m: float
  requested_curvature_1_per_m: float
  tesla_max_abs_curvature_1_per_m: float
  desired_angle_deg: float
  jerk_delta_deg: float
  max_angle_rate_deg: float
  accel_max_angle_deg: float
  steer_angle_max_deg: float
  frames: int
  dt_s: float
  steps: tuple[AngleLimitStep, ...]
  time_to_90pct_s: float | None
  reached_90pct: bool
  final_angle_deg: float

  @property
  def curvature_cap_widens_radius(self) -> bool:
    return abs(self.requested_curvature_1_per_m) > self.tesla_max_abs_curvature_1_per_m + 1e-9


def steer_response(speed_m_s: float, radius_m: float = ARC_RADIUS_M, blinker: bool = True, frames: int = DEFAULT_FRAMES) -> TeslaSteerResponse:
  """One synthetic left arc at constant speed, from 0 deg toward the desired angle.

  Curvature comes from wide_turn_stage_harness.diagnose. The desired angle uses
  the same speed for LatControlAngle's vEgo and for the limiter's vEgoRaw.
  Blinker true selects the pause-on-signal correction inside diagnose.
  """
  if frames < 1:
    raise ValueError("frames must be at least 1")

  stages = diagnose(speed_m_s, radius_m=radius_m, blinker=blinker)
  vm = model_y_vehicle_model()
  cp = get_safety_CP()
  specs = CAR.TESLA_MODEL_Y.config.specs
  desired = latcontrol_angle_desired_deg(stages.requested_curvature_1_per_m, speed_m_s, vm)
  v_ego = max(float(speed_m_s), 1.0)
  jerk_delta = float(get_max_angle_delta_vm(v_ego, vm, CarControllerParams))
  rate_cap = float(CarControllerParams.ANGLE_LIMITS.MAX_ANGLE_RATE)
  accel_max = float(get_max_angle_vm(v_ego, vm, CarControllerParams))
  dt = command_dt_s()

  angle = 0.0
  steps: list[AngleLimitStep] = []
  time_to_90 = None
  target_90 = 0.9 * desired
  for index in range(frames):
    binder, accel_clip, angle = classify_first_binder(desired, angle, speed_m_s, vm)
    if binder not in BINDER_NAMES:
      raise RuntimeError(f"unnamed binder {binder}")
    time_s = (index + 1) * dt
    steps.append(AngleLimitStep(index + 1, time_s, angle, binder, accel_clip))
    if time_to_90 is None and desired != 0.0 and angle * desired > 0.0 and abs(angle) >= abs(target_90) - 1e-6:
      time_to_90 = time_s

  return TeslaSteerResponse(
    label=INVESTIGATION_LABEL,
    speed_m_s=float(speed_m_s),
    radius_m=float(radius_m),
    blinker=bool(blinker),
    cooperative_steering_active=model_y_uses_cooperative_steering(),
    roll_rad=0.0,
    angle_offset_deg=0.0,
    spec_mass_kg=float(specs.mass),
    vehicle_model_mass_kg=float(cp.mass),
    wheelbase_m=float(specs.wheelbase),
    steer_ratio=float(specs.steerRatio),
    model_curvature_1_per_m=float(stages.model_curvature_1_per_m),
    requested_curvature_1_per_m=float(stages.requested_curvature_1_per_m),
    tesla_max_abs_curvature_1_per_m=float(stages.tesla_max_abs_curvature_1_per_m),
    desired_angle_deg=float(desired),
    jerk_delta_deg=jerk_delta,
    max_angle_rate_deg=rate_cap,
    accel_max_angle_deg=accel_max,
    steer_angle_max_deg=float(CarControllerParams.ANGLE_LIMITS.STEER_ANGLE_MAX),
    frames=int(frames),
    dt_s=dt,
    steps=tuple(steps),
    time_to_90pct_s=time_to_90,
    reached_90pct=time_to_90 is not None,
    final_angle_deg=float(angle),
  )


def steer_response_grid(
  speeds_m_s: tuple[float, ...] = SPEEDS_M_S, radius_m: float = ARC_RADIUS_M, blinker: bool = True, frames: int = DEFAULT_FRAMES
) -> tuple[TeslaSteerResponse, ...]:
  return tuple(steer_response(speed, radius_m=radius_m, blinker=blinker, frames=frames) for speed in speeds_m_s)


def format_grid(reports: tuple[TeslaSteerResponse, ...]) -> str:
  """Compact text for the audit table. Not a road result."""
  lines = [reports[0].label if reports else INVESTIGATION_LABEL, ""]
  header = (
    f"{'v':>6} {'model':>9} {'requested':>10} {'desired':>9} {'jerk_d':>8} " + f"{'rate':>6} {'accel_max':>9} {'t90':>8} {'final':>9} {'cap':>5} {'first':>16}"
  )
  lines.append(header)
  for report in reports:
    t90 = "none" if report.time_to_90pct_s is None else f"{report.time_to_90pct_s:.2f}"
    widened = "yes" if report.curvature_cap_widens_radius else "no"
    lines.append(
      f"{report.speed_m_s:6.1f} {report.model_curvature_1_per_m:9.5f} "
      + f"{report.requested_curvature_1_per_m:10.5f} {report.desired_angle_deg:9.3f} "
      + f"{report.jerk_delta_deg:8.4f} {report.max_angle_rate_deg:6.1f} "
      + f"{report.accel_max_angle_deg:9.3f} {t90:>8} {report.final_angle_deg:9.3f} "
      + f"{widened:>5} {report.steps[0].first_binder:>16}"
    )
  return "\n".join(lines)


if __name__ == "__main__":
  print(format_grid(steer_response_grid()))
