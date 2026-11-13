"""Path steering uses recent model plans only when the toggle is on."""

import ast
import struct
from collections.abc import Callable
from pathlib import Path
from typing import cast

import numpy as np
import pytest

from openpilot.cereal import log
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.drive_helpers import get_accel_from_plan, get_curvature_from_plan, should_stop, smooth_value
from openpilot.selfdrive.modeld.constants import LAT_SMOOTH_SECONDS, ModelConstants, Plan
from openpilot.selfdrive.modeld.path_steering import (
  FADE_OUT_MPH, FULL_ON_MPH, HISTORY_S, KEY, MODE_BLEND_S, MPH_TO_MS, TURN_WINDOW_S, PathSteering,
)
from openpilot.starpilot.models.runner import action_from_outputs


def get_action_from_model(*args, **kwargs):
  """The modeld function, without importing modeld (that import needs the device IPC library)."""
  source = Path(__file__).resolve().parents[1] / "modeld.py"
  function = next(node for node in ast.parse(source.read_text()).body
                  if isinstance(node, ast.FunctionDef) and node.name == "get_action_from_model")
  namespace = {"np": np, "log": log, "smooth_value": smooth_value, "should_stop": should_stop,
               "get_accel_from_plan": get_accel_from_plan, "get_curvature_from_plan": get_curvature_from_plan,
               "Plan": Plan, "ModelConstants": ModelConstants,
               "LONG_SMOOTH_SECONDS": 0.3, "LAT_SMOOTH_SECONDS": LAT_SMOOTH_SECONDS,
               "MIN_LAT_CONTROL_SPEED": 0.3}
  exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
  function = cast(Callable, namespace["get_action_from_model"])
  return function(*args, **kwargs)


def bits(value):
  return struct.pack("<d", float(value))


def mph(speed):
  return speed * MPH_TO_MS


def constant_plan(curvature):
  count = ModelConstants.IDX_N
  distance = np.linspace(0.0, 128.0, count)
  plan = np.zeros((count, ModelConstants.PLAN_WIDTH))
  plan[:, 0] = distance
  plan[:, 3] = 10.0
  plan[:, 14] = curvature * 10.0
  return plan


def distance_plan(slope):
  """Curvature equals slope times distance along a straight path."""
  count = ModelConstants.IDX_N
  distance = np.arange(count, dtype=float) * 4.0
  plan = np.zeros((count, ModelConstants.PLAN_WIDTH))
  plan[:, 0] = distance
  plan[:, 3] = 10.0
  plan[:, 14] = slope * distance * 10.0
  return plan


def engage(steering, plan, speed, action=0.0, desire=1):
  """One half-second step, enough to finish the mode blend."""
  return steering.adjust(action, plan, speed, 0.4, desire, MODE_BLEND_S)


class Boom:
  enabled = True
  called = False

  def adjust(self, *_args, **_kwargs):
    self.called = True
    raise AssertionError("this model has no action output")


def test_constants_match_the_requested_windows():
  assert (FULL_ON_MPH, FADE_OUT_MPH, MODE_BLEND_S, TURN_WINDOW_S, HISTORY_S) == (20.0, 29.0, 0.5, 6.6, 1.0)


def test_toggle_off_matches_the_action_curvature_exactly():
  previous = log.ModelDataV2.Action(desiredCurvature=0.01, desiredAcceleration=0.1)
  outputs = {"action": np.array([[0.25, 0.5]]), "plan": constant_plan(0.2)[None]}
  disabled = PathSteering(enabled=False)
  for speed in (0.0, 0.31, mph(10), mph(24.5), mph(40)):
    baseline = get_action_from_model(outputs, previous, 0.2, 0.2, speed)
    untouched = get_action_from_model(outputs, previous, 0.2, 0.2, speed)
    held = get_action_from_model(outputs, previous, 0.2, 0.2, speed, path_steering=disabled, desire=1, dt=0.05)
    assert bits(baseline.desiredCurvature) == bits(untouched.desiredCurvature) == bits(held.desiredCurvature)
    assert bits(baseline.desiredAcceleration) == bits(held.desiredAcceleration)
    assert baseline.shouldStop == held.shouldStop


def test_plan_only_models_ignore_path_steering():
  previous = log.ModelDataV2.Action(desiredCurvature=0.01, desiredAcceleration=0.1)
  plan = np.zeros((1, ModelConstants.IDX_N, ModelConstants.PLAN_WIDTH))
  plan[0, :, 3] = 8.0
  plan[0, :, 11] = np.linspace(0.0, 0.4, ModelConstants.IDX_N)
  outputs = {"plan": plan}
  boom = Boom()
  baseline = get_action_from_model(outputs, previous, 0.4, 0.4, mph(10))
  steered = get_action_from_model(outputs, previous, 0.4, 0.4, mph(10), path_steering=boom, desire=1, dt=0.05)
  assert not boom.called
  assert bits(baseline.desiredCurvature) == bits(steered.desiredCurvature)
  assert bits(baseline.desiredAcceleration) == bits(steered.desiredAcceleration)
  legacy = {"plan": plan, "desired_curvature": np.array([[0.03]])}
  before = action_from_outputs(legacy, "v9", previous, 0.2, 0.2, 20.0)
  after = action_from_outputs(legacy, "v9", previous, 0.2, 0.2, 20.0, path_steering=boom, desire=1, dt=0.05)
  assert not boom.called
  assert bits(before.desiredCurvature) == bits(after.desiredCurvature)
  assert bits(before.desiredAcceleration) == bits(after.desiredAcceleration)


def test_speed_fade_is_full_through_20_mph_and_gone_at_29():
  plan = constant_plan(0.1)
  low = PathSteering(enabled=True)
  full = engage(low, plan, mph(20))
  assert full == pytest.approx(0.1)
  assert engage(PathSteering(enabled=True), plan, mph(19)) == pytest.approx(0.1)
  high = PathSteering(enabled=True)
  above = engage(high, plan, mph(29), action=0.02)
  assert bits(above) == bits(0.02)
  assert bits(engage(PathSteering(enabled=True), plan, mph(40), action=0.02)) == bits(0.02)
  mid = PathSteering(enabled=True)
  blended = engage(mid, plan, mph(24.5))
  assert blended == pytest.approx(0.05)


def test_modes_blend_over_half_a_second():
  plan = constant_plan(0.1)
  steering = PathSteering(enabled=True)
  speed = mph(10)
  first = steering.adjust(0.0, plan, speed, 0.4, 1, 0.25)
  assert first == pytest.approx(0.05)
  second = steering.adjust(0.0, plan, speed, 0.4, 1, 0.25)
  assert second == pytest.approx(0.1)


def test_turn_desire_window_lasts_about_6_6_seconds():
  plan = constant_plan(0.1)
  steering = PathSteering(enabled=True)
  speed = mph(10)
  assert engage(steering, plan, speed, desire=1) == pytest.approx(0.1)
  assert steering.adjust(0.0, plan, speed, 0.4, 0, 6.1) == pytest.approx(0.1)
  assert steering.adjust(0.0, plan, speed, 0.4, 0, DT_MDL) == pytest.approx(0.1)
  faded = steering.adjust(0.0, plan, speed, 0.4, 0, 0.25)
  assert faded == pytest.approx(0.05)
  lane_change = PathSteering(enabled=True)
  assert engage(lane_change, plan, speed, action=0.0, desire=3) == pytest.approx(0.0)


def test_lookup_uses_distance_driven_since_the_plan():
  slope = 0.001
  plan = distance_plan(slope)
  steering = PathSteering(enabled=True)
  speed = 5.0  # under 20 mph, so the speed fade does not scale the looked-up curvature
  delay = 0.4
  first = steering.adjust(0.0, plan, speed, delay, 1, MODE_BLEND_S)
  assert first == pytest.approx(slope * speed * delay)
  driven = speed * MODE_BLEND_S
  second = steering.adjust(0.0, plan, speed, delay, 1, DT_MDL)
  expected = slope * ((driven + speed * delay) + (speed * delay)) / 2.0
  assert second == pytest.approx(expected)
  assert second != pytest.approx(first)


def test_plans_never_start_a_turn_without_a_turn_desire():
  speed = mph(10)
  straight_action = PathSteering(enabled=True)
  for _ in range(30):
    assert straight_action.adjust(0.0, constant_plan(0.25), speed, 0.4, 0, DT_MDL) == 0.0
  level = PathSteering(enabled=True)
  assert engage(level, constant_plan(0.25), speed, action=0.02, desire=0) == pytest.approx(0.02)
  shaped = PathSteering(enabled=True)
  assert shaped.adjust(0.02, constant_plan(0.30), speed, 0.4, 0, DT_MDL) == pytest.approx(0.02)
  scaled = shaped.adjust(0.02, constant_plan(0.10), speed, 0.4, 0, DT_MDL)
  assert scaled == pytest.approx(0.02 * (0.10 / 0.20))
  opposed = PathSteering(enabled=True)
  opposed.adjust(0.02, constant_plan(0.20), speed, 0.4, 0, DT_MDL)
  assert opposed.adjust(0.02, constant_plan(-0.10), speed, 0.4, 0, DT_MDL) == pytest.approx(0.02)


def test_old_plans_leave_the_one_second_history():
  steering = PathSteering(enabled=True)
  speed = mph(10)
  engage(steering, constant_plan(0.2), speed)
  assert steering.adjust(0.0, constant_plan(0.0), speed, 0.4, 1, HISTORY_S) == pytest.approx(0.1)
  assert steering.adjust(0.0, constant_plan(0.0), speed, 0.4, 1, DT_MDL) == pytest.approx(0.0)


def test_catalog_action_models_keep_acceleration_and_gain_path_curvature():
  previous = log.ModelDataV2.Action(desiredCurvature=0.02, desiredAcceleration=0.1)
  outputs = {"action": np.array([[4.0, 0.5]]), "plan": constant_plan(0.08)[None]}
  baseline = action_from_outputs(outputs, "v15", previous, 0.2, 0.2, mph(15))
  steering = PathSteering(enabled=True)
  steered = action_from_outputs(outputs, "v15", previous, 0.2, 0.2, mph(15),
                                path_steering=steering, desire=1, dt=MODE_BLEND_S)
  assert steered.desiredCurvature == pytest.approx(0.08)
  assert bits(steered.desiredAcceleration) == bits(baseline.desiredAcceleration)
  assert steered.shouldStop == baseline.shouldStop
  assert steered.desiredCurvature != pytest.approx(baseline.desiredCurvature)


def test_saved_toggle_is_off_until_the_file_says_on(tmp_path):
  class Store:
    def get_param_path(self, key):
      assert key == KEY
      return str(tmp_path / key)

  from openpilot.selfdrive.modeld.path_steering import PathSteeringPreferences
  preferences = PathSteeringPreferences(Store())
  assert preferences.sample(0) is False
  (tmp_path / KEY).write_bytes(b"1")
  assert preferences.sample(1_000_000_000) is True
  (tmp_path / KEY).write_bytes(b"0")
  assert preferences.sample(2_000_000_000) is False


def test_registered_toggle_defaults_off():
  root = Path(__file__).resolve().parents[3]
  header = (root / "common" / "params_keys.h").read_text()
  owner = (root / "starpilot" / "ui" / "feature_settings_owner.py").read_text()
  descriptions = (root / "starpilot" / "galaxy" / "setting_descriptions.py").read_text()
  assert '{"PathSteering", {PERSISTENT, BOOL, "0"}}' in header
  assert KEY == "PathSteering"
  assert '"PathSteering": False' in owner
  assert '"PathSteering"' in owner.split("GLOBAL_BOOL_PREFERENCES", 1)[1].split("BOOL_DEFAULTS", 1)[0]
  assert "Steers from the driving model's recent path" in descriptions
