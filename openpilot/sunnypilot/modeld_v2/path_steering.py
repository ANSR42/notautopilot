"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import numpy as np

from openpilot.common.constants import CV
from openpilot.sunnypilot.modeld_v2.constants import Plan

# log.Desire values. Lane-change desires are intentionally not in this set.
DESIRE_TURN_LEFT = 1
DESIRE_TURN_RIGHT = 2
DESIRE_LANE_CHANGE_LEFT = 3
TURN_DESIRES = (DESIRE_TURN_LEFT, DESIRE_TURN_RIGHT)

PLAN_HISTORY_S = 1.0
TURN_DESIRE_HOLD_S = 6.6
MODE_FADE_S = 0.5
FULL_ON_MPH = 20.0
FADE_OUT_MPH = 29.0
_LEVEL_EPS = 1e-9


def plan_curvature_at(plan: np.ndarray, distance: float) -> float:
  """Geometric curvature (dψ/dx) of a model plan at a distance along its x."""
  x = np.asarray(plan[:, Plan.POSITION][:, 0], dtype=np.float64)
  yaw = np.asarray(plan[:, Plan.T_FROM_CURRENT_EULER][:, 2], dtype=np.float64)
  if x.shape[0] < 2:
    return 0.0
  x = np.maximum.accumulate(x)
  dx = np.diff(x)
  if np.any(dx <= 0.0):
    x = x + np.arange(x.shape[0], dtype=np.float64) * 1e-6
    dx = np.diff(x)
  seg_k = np.diff(yaw) / dx
  mid = x[:-1] + dx * 0.5
  return float(np.interp(distance, mid, seg_k))


class PathSteering:
  """Blend the driving model's action curvature with its recent plans.

  Toggle off, or a model with no action output, returns the curvature it was
  given and does not touch internal state. With the toggle on:

  - keep each plan from the last second
  - read the curvature that plan expects where the car will be when the
    steering arrives: distance driven since the plan, plus v * lat_action_t
    (the delay modeld already passes as the action time)
  - while turnLeft/turnRight reached the model in the last 6.6 s, steer from
    the average of those curvatures
  - otherwise the action sets the level and the plans only scale its shape,
    so a straight action stays straight
  - fully on at 20 mph and below, gone at 29 mph and above
  - the two modes crossfade over 0.5 s
  """

  def __init__(self):
    self.enabled = False
    self.t = 0.0
    self.distance = 0.0
    self.since_turn = 1e9
    self.mode = 0.0
    self._history: list[tuple[float, float, np.ndarray]] = []

  def update(self, *, enabled: bool, has_action: bool, action_curvature: float, plan: np.ndarray | None,
             v_ego: float, lat_action_t: float, desire: int, dt: float) -> float:
    if not enabled or not has_action:
      return action_curvature

    self.t += dt
    self.distance += max(v_ego, 0.0) * dt
    if plan is not None:
      self._history.append((self.t, self.distance, np.array(plan, dtype=np.float64, copy=True)))
    self._history = [item for item in self._history if self.t - item[0] <= PLAN_HISTORY_S + 1e-9]
    if desire in TURN_DESIRES:
      self.since_turn = 0.0
    else:
      self.since_turn += dt

    if not self._history:
      return action_curvature

    lookahead = max(v_ego, 0.0) * max(lat_action_t, 0.0)
    curvs = [plan_curvature_at(stored, (self.distance - planned_at) + lookahead)
             for _t, planned_at, stored in self._history]
    plan_level = float(np.mean(curvs))
    if abs(action_curvature) < _LEVEL_EPS or abs(plan_level) < _LEVEL_EPS:
      no_turn = action_curvature
    else:
      no_turn = action_curvature * (curvs[-1] / plan_level)

    target = 1.0 if self.since_turn <= TURN_DESIRE_HOLD_S else 0.0
    step = dt / MODE_FADE_S if MODE_FADE_S > 0.0 else 1.0
    if self.mode < target:
      self.mode = min(target, self.mode + step)
    else:
      self.mode = max(target, self.mode - step)
    blended = (1.0 - self.mode) * no_turn + self.mode * plan_level

    speed_w = float(np.interp(v_ego, [FULL_ON_MPH * CV.MPH_TO_MS, FADE_OUT_MPH * CV.MPH_TO_MS], [1.0, 0.0]))
    if speed_w <= 0.0:
      return action_curvature
    if speed_w >= 1.0:
      return blended
    return (1.0 - speed_w) * action_curvature + speed_w * blended
