"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import os
import unittest

import numpy as np

from openpilot.common.constants import CV
from openpilot.sunnypilot.modeld_v2.path_steering import (
  DESIRE_LANE_CHANGE_LEFT,
  DESIRE_TURN_LEFT,
  DESIRE_TURN_RIGHT,
  MODE_FADE_S,
  PLAN_HISTORY_S,
  TURN_DESIRE_HOLD_S,
  PathSteering,
  plan_curvature_at,
)

DT = 0.05  # modeld DT_MDL, 20 Hz
# Plan yaw = 0.005 x^2 so geometric curvature is 0.01 * x on the interior.
CURV_PER_METER = 0.01


def mph(miles_per_hour: float) -> float:
  return miles_per_hour * CV.MPH_TO_MS


def constant_plan(curvature: float, n: int = 33, length: float = 80.0) -> np.ndarray:
  xs = np.linspace(0.0, length, n)
  plan = np.zeros((n, 15))
  plan[:, 0] = xs
  plan[:, 11] = curvature * xs
  return plan


def distance_encoded_plan() -> np.ndarray:
  xs = np.arange(0.0, 41.0, 1.0)
  plan = np.zeros((len(xs), 15))
  plan[:, 0] = xs
  plan[:, 11] = 0.5 * CURV_PER_METER * xs ** 2
  return plan


def step(ps: PathSteering, n: int, **kwargs) -> float:
  kwargs.setdefault("dt", DT)
  kwargs.setdefault("enabled", True)
  kwargs.setdefault("has_action", True)
  kwargs.setdefault("lat_action_t", 0.3)
  kwargs.setdefault("desire", 0)
  kwargs.setdefault("v_ego", mph(10))
  out = 0.0
  for _ in range(n):
    out = ps.update(**kwargs)
  return out


class TestPathSteering(unittest.TestCase):
  def test_toggle_off_is_identity(self):
    ps = PathSteering()
    action = 0.01337
    plan = constant_plan(0.2)
    for _ in range(40):
      out = ps.update(enabled=False, has_action=True, action_curvature=action, plan=plan,
                      v_ego=mph(5), lat_action_t=0.4, desire=DESIRE_TURN_LEFT, dt=DT)
      assert out is action

  def test_speed_fade_20_to_29_mph(self):
    plan = constant_plan(0.04)
    action = 0.0

    def settled(speed, action_curvature=action):
      ps = PathSteering()
      # crossfade into turn mode, then sample at this speed
      step(ps, int(MODE_FADE_S / DT), action_curvature=action_curvature, plan=plan, desire=DESIRE_TURN_LEFT, v_ego=mph(10))
      return ps.update(enabled=True, has_action=True, action_curvature=action_curvature, plan=plan,
                       v_ego=speed, lat_action_t=0.3, desire=DESIRE_TURN_LEFT, dt=DT)

    assert abs(settled(mph(10)) - 0.04) < 1e-9
    assert abs(settled(mph(20)) - 0.04) < 1e-9
    assert abs(settled(mph(24.5)) - 0.02) < 1e-9
    high_action = 0.007
    assert settled(mph(29), high_action) is high_action
    assert settled(mph(40), high_action) is high_action

  def test_no_turn_plans_cannot_create_curvature(self):
    ps = PathSteering()
    action = 0.0
    # constant curve the action did not ask for
    out = step(ps, 30, action_curvature=action, plan=constant_plan(0.05), desire=0, v_ego=mph(8))
    assert out == 0.0
    # plans that change shape still cannot leave zero when the action is zero
    for k in (0.02, -0.08, 0.15, -0.01, 0.04):
      out = ps.update(enabled=True, has_action=True, action_curvature=action, plan=constant_plan(k),
                      v_ego=mph(8), lat_action_t=0.3, desire=0, dt=DT)
      assert out == 0.0

  def test_no_turn_action_sets_level_plans_set_shape(self):
    ps = PathSteering()
    action = 0.02
    # constant plans: shape is flat, level stays the action
    out = step(ps, 20, action_curvature=action, plan=constant_plan(0.05), desire=0, v_ego=mph(12))
    assert abs(out - action) < 1e-9
    # latest plan is 1.5x the window mean -> output is 1.5x the action
    ps = PathSteering()
    step(ps, 10, action_curvature=action, plan=constant_plan(0.01), desire=0, v_ego=mph(12))
    out = step(ps, 10, action_curvature=action, plan=constant_plan(0.03), desire=0, v_ego=mph(12))
    assert abs(out - 0.03) < 1e-9

  def test_turn_desire_hold_and_half_second_crossfade(self):
    plan = constant_plan(0.04)
    action = 0.01
    ps = PathSteering()
    # no desire yet: flat plans, so output is the action
    out = step(ps, 5, action_curvature=action, plan=plan, desire=0)
    assert abs(out - action) < 1e-9

    # half-second crossfade into the plan average
    mid = step(ps, int(0.25 / DT), action_curvature=action, plan=plan, desire=DESIRE_TURN_RIGHT)
    assert abs(mid - 0.025) < 1e-9
    full = step(ps, int(0.25 / DT), action_curvature=action, plan=plan, desire=DESIRE_TURN_RIGHT)
    assert abs(full - 0.04) < 1e-9

    # desire drops. stay on the plan until ~6.6 s, then fade back over 0.5 s
    held = step(ps, int(6.5 / DT), action_curvature=action, plan=plan, desire=0)
    assert abs(held - 0.04) < 1e-9
    released = step(ps, int(0.7 / DT), action_curvature=action, plan=plan, desire=0)
    assert abs(released - action) < 1e-9
    assert TURN_DESIRE_HOLD_S == 6.6
    assert MODE_FADE_S == 0.5

  def test_lane_change_desire_is_not_a_turn(self):
    ps = PathSteering()
    action = 0.0
    out = step(ps, int((TURN_DESIRE_HOLD_S + MODE_FADE_S) / DT) + 5,
               action_curvature=action, plan=constant_plan(0.08), desire=DESIRE_LANE_CHANGE_LEFT, v_ego=mph(8))
    assert out == 0.0

  def test_distance_based_plan_lookup(self):
    # curvature encodes distance: k(x) = 0.01 * x. A time-based index of the same
    # plans lands elsewhere because speed is not constant and x is not v*t.
    plan = distance_encoded_plan()
    assert abs(plan_curvature_at(plan, 15.0) - 0.15) < 1e-9
    assert abs(plan_curvature_at(plan, 4.0) - 0.04) < 1e-9

    ps = PathSteering()
    # one frame completes the crossfade without moving (v = 0) and ages out later
    ps.update(enabled=True, has_action=True, action_curvature=0.0, plan=constant_plan(0.0),
              v_ego=0.0, lat_action_t=0.5, desire=DESIRE_TURN_LEFT, dt=MODE_FADE_S)

    lat = 0.5
    frames = [(20.0, 10), (4.0, 12)]  # 0.5 s at 20 m/s, then 0.6 s at 4 m/s
    distance = 0.0
    t = MODE_FADE_S
    recorded: list[tuple[float, float]] = []
    out = 0.0
    for speed, count in frames:
      for _ in range(count):
        t += DT
        distance += speed * DT
        recorded.append((t, distance))
        out = ps.update(enabled=True, has_action=True, action_curvature=0.0, plan=plan,
                        v_ego=speed, lat_action_t=lat, desire=DESIRE_TURN_LEFT, dt=DT)
    live = [(t - pt, distance - pd) for pt, pd in recorded if t - pt <= PLAN_HISTORY_S + 1e-9]
    current_speed = frames[-1][0]
    lookups = [driven + current_speed * lat for _age, driven in live]
    expected = float(np.mean([CURV_PER_METER * x for x in lookups]))
    assert abs(out - expected) < 1e-9
    # the oldest live plan was made at high speed; current speed * its age is not the distance driven
    oldest_age, oldest_driven = live[0]
    assert abs(oldest_driven - frames[-1][0] * oldest_age) > 1.0

  def test_model_without_action_is_unchanged(self):
    ps = PathSteering()
    plan_curvature = 0.333
    wild = constant_plan(0.2)
    for _ in range(30):
      out = ps.update(enabled=True, has_action=False, action_curvature=plan_curvature, plan=wild,
                      v_ego=mph(5), lat_action_t=0.4, desire=DESIRE_TURN_LEFT, dt=DT)
      assert out is plan_curvature
    # those frames must not leak into a later action model
    straight = constant_plan(0.0)
    out = step(ps, 5, action_curvature=0.02, plan=straight, desire=0, v_ego=mph(10))
    assert abs(out - 0.02) < 1e-9

  def test_scripted_low_speed_corner(self):
    """Offline stand-in for a replay: a slow corner, then the blinker drops, then speed rises."""
    ps = PathSteering()
    action = 0.0
    curve = constant_plan(0.03)
    straight = constant_plan(0.0)
    # no blinker, plan wants a curve, action does not: stay straight
    for _ in range(20):
      out = ps.update(enabled=True, has_action=True, action_curvature=action, plan=curve,
                      v_ego=mph(12), lat_action_t=0.25, desire=0, dt=DT)
    assert out == 0.0
    # blinker turn desire: fade onto the plan
    for _ in range(int(MODE_FADE_S / DT)):
      out = ps.update(enabled=True, has_action=True, action_curvature=action, plan=curve,
                      v_ego=mph(12), lat_action_t=0.25, desire=DESIRE_TURN_LEFT, dt=DT)
    assert abs(out - 0.03) < 1e-9
    # blinker off, still inside the hold
    for _ in range(int(6.0 / DT)):
      out = ps.update(enabled=True, has_action=True, action_curvature=action, plan=curve,
                      v_ego=mph(12), lat_action_t=0.25, desire=0, dt=DT)
    assert abs(out - 0.03) < 1e-9
    # up to highway speed the plan no longer steers, even mid-hold
    out = ps.update(enabled=True, has_action=True, action_curvature=0.004, plan=curve,
                    v_ego=mph(35), lat_action_t=0.25, desire=DESIRE_TURN_LEFT, dt=DT)
    assert out == 0.004
    # back to a straight action with the toggle off
    out = ps.update(enabled=False, has_action=True, action_curvature=0.004, plan=straight,
                    v_ego=mph(12), lat_action_t=0.25, desire=DESIRE_TURN_LEFT, dt=DT)
    assert out == 0.004

  def test_param_and_settings_registered(self):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    with open(os.path.join(root, "openpilot/common/params_keys.h"), encoding="utf-8") as f:
      keys = f.read()
    assert '{"PathSteering", {PERSISTENT | BACKUP, BOOL, "0"}}' in keys
    with open(os.path.join(root, "openpilot/sunnypilot/sunnylink/settings_ui.json"), encoding="utf-8") as f:
      settings = f.read()
    assert '"key": "PathSteering"' in settings
