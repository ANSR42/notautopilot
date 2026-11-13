"""Low-speed steering from the driving model's recent plans.

The action output still sets the curvature above about 29 mph, and for any
model that has no action output. Below about 20 mph, a turn desire that
reached the model in the last 6.6 s selects the average plan curvature.
Without one, the action keeps the level and the plans only scale its shape,
so a plan cannot start a turn by itself. The two modes crossfade in 0.5 s.
"""

import math

import numpy as np

from openpilot.selfdrive.modeld.constants import ModelConstants, Plan


KEY = "PathSteering"
LABEL = "Path Steering"
REASON = ("Steers from the driving model's recent path at low speed while a turn is signalled, " +
          "and otherwise uses that path only to shape the model's steering. Fades out by about 29 mph.")

FULL_ON_MPH = 20.0
FADE_OUT_MPH = 29.0
MPH_TO_MS = 0.44704
HISTORY_S = 1.0
TURN_WINDOW_S = 6.6
MODE_BLEND_S = 0.5
# cereal Desire.turnLeft and Desire.turnRight. Lane changes are not turns.
_TURN_DESIRES = frozenset((1, 2))
_MIN_PLAN_SPEED = 1.0


class _PlanSample:
  def __init__(self, stamp_s, distance_m, arc, curvature):
    self.stamp_s = stamp_s
    self.distance_m = distance_m
    self.arc = arc
    self.curvature = curvature


def _speed_weight(speed):
  low = FULL_ON_MPH * MPH_TO_MS
  high = FADE_OUT_MPH * MPH_TO_MS
  if speed <= low:
    return 1.0
  if speed >= high:
    return 0.0
  return (high - speed) / (high - low)


def _profile(plan):
  array = np.asarray(plan, dtype=np.float64)
  if array.ndim == 3 and array.shape[0] == 1:
    array = array[0]
  if array.shape != (ModelConstants.IDX_N, ModelConstants.PLAN_WIDTH) or not np.isfinite(array).all():
    return None
  position = array[:, Plan.POSITION]
  step = np.hypot(np.diff(position[:, 0]), np.diff(position[:, 1]))
  arc = np.maximum.accumulate(np.concatenate((np.zeros(1), np.cumsum(step))))
  velocity = array[:, Plan.VELOCITY]
  speed = np.maximum(np.hypot(velocity[:, 0], velocity[:, 1]), _MIN_PLAN_SPEED)
  curvature = array[:, Plan.ORIENTATION_RATE][:, 2] / speed
  if not np.isfinite(curvature).all() or not np.isfinite(arc).all():
    return None
  return arc, curvature


def _cruise(action, samples):
  """Action sets the level. A same-sign plan ratio sets the shape and cannot create a turn."""
  if not samples or action == 0.0:
    return action
  center = math.fsum(samples) / len(samples)
  latest = samples[-1]
  if center == 0.0 or latest * center <= 0.0:
    return action
  return action * (latest / center)


class PathSteering:
  def __init__(self, enabled=False):
    self.enabled = bool(enabled)
    self._plans = []
    self._t = 0.0
    self._distance = 0.0
    self._turn_until = -math.inf
    self._mode = 0.0

  def reset(self):
    self._plans = []
    self._t = 0.0
    self._distance = 0.0
    self._turn_until = -math.inf
    self._mode = 0.0

  def adjust(self, action_curvature, plan, v_ego, lat_action_t, desire, dt):
    if not self.enabled:
      return action_curvature
    try:
      action = float(action_curvature)
      speed = float(v_ego)
      delay = float(lat_action_t)
      step = float(dt)
      desire_value = int(desire)
    except (TypeError, ValueError, OverflowError):
      return action_curvature
    if not all(math.isfinite(value) for value in (action, speed, delay, step)):
      return action_curvature
    step = max(0.0, step)
    speed = max(0.0, speed)
    delay = max(0.0, delay)

    profile = _profile(plan)
    if profile is not None:
      arc, curvature = profile
      self._plans.append(_PlanSample(self._t, self._distance, arc, curvature))
    self._plans = [item for item in self._plans if self._t - item.stamp_s <= HISTORY_S]

    if desire_value in _TURN_DESIRES:
      self._turn_until = self._t + TURN_WINDOW_S
    active = self._t <= self._turn_until
    blend = 0.0 if MODE_BLEND_S <= 0.0 else step / MODE_BLEND_S
    if active:
      self._mode = min(1.0, self._mode + blend)
    else:
      self._mode = max(0.0, self._mode - blend)

    samples = []
    for item in self._plans:
      ahead = (self._distance - item.distance_m) + speed * delay
      samples.append(float(np.interp(ahead, item.arc, item.curvature)))
    turn = math.fsum(samples) / len(samples) if samples else action
    mixed = (1.0 - self._mode) * _cruise(action, samples) + self._mode * turn
    self._t += step
    self._distance += speed * step

    weight = _speed_weight(speed)
    if weight == 0.0:
      return action_curvature
    if weight == 1.0:
      return mixed
    return (1.0 - weight) * action + weight * mixed


class PathSteeringPreferences:
  """Read the saved toggle about once a second. A missing or unknown key stays off."""

  def __init__(self, params):
    self.params = params
    self.enabled = False
    self._next_ns = 0
    self._last_ns = 0

  def sample(self, now_ns):
    try:
      now_ns = int(now_ns)
    except (TypeError, ValueError, OverflowError):
      self.enabled = False
      return False
    if now_ns < self._last_ns:
      self._next_ns = 0
    self._last_ns = now_ns
    if now_ns >= self._next_ns:
      self._next_ns = now_ns + 1_000_000_000
      self.enabled = _read_enabled(self.params)
    return self.enabled


def _read_enabled(params) -> bool:
  """Off unless the saved file is exactly b'1'.

  The file read does not require the key to already be in the prebuilt params
  library. A missing file stays off, matching the registry default.
  """
  try:
    from openpilot.starpilot.saved_source import read_saved
    raw, readable = read_saved(params, KEY, 16)
  except (OSError, TypeError, ValueError, OverflowError, AttributeError):
    return False
  return bool(readable and raw == b"1")
