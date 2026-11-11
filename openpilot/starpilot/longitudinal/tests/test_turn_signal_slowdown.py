"""Blinker-gated port of the StarPilot 6.7.9 Taco Bell curvature speed cap."""

from pathlib import Path

import pytest

from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR
from openpilot.common.params import UnknownKeyName
from openpilot.selfdrive.controls.lib.longitudinal_planner import A_CRUISE_MIN, LongitudinalPlanner
from openpilot.starpilot.longitudinal.tests.test_cruise_ceiling import V_EGO, messages
from openpilot.starpilot.longitudinal.turn_signal_slowdown import (
  KEY, TurnSignalPreferences, curvature_speed_cap, read_enabled, turn_signal_ceiling, write_enabled,
)

# v_ego 20, constant yaw 0.5 rad/s, model speed 20: sqrt(3 / (0.025 + 1e-3)) - 2
TIGHT_YAW = 0.5
EXPECTED_CAP = 8.741723110591492
FRAMES = 12


def _model(speed, yaw):
  return [float(speed)] * 33, [float(yaw)] * 33


def test_curvature_cap_matches_taco_formula_and_floors_at_zero():
  speeds, rates = _model(20.0, TIGHT_YAW)
  assert curvature_speed_cap(20.0, rates, speeds) == pytest.approx(EXPECTED_CAP)
  # A u-turn-sized yaw makes the 6.7.9 expression negative. The ceiling may only slow to 0.
  assert curvature_speed_cap(5.0, [2.0] * 33, [5.0] * 33) == 0.0
  assert curvature_speed_cap(20.0, [0.5] * 10, [20.0] * 10) is None
  assert curvature_speed_cap(float("nan"), rates, speeds) is None


def _scene(cp, *, blinker="left", yaw=TIGHT_YAW, e2e=False, gas=False, gear="drive", long_active=True, enabled=True):
  sm, _ = messages(e2e=e2e)
  car = sm["carState"]
  car.vEgo = V_EGO
  car.gearShifter = gear
  car.leftBlinker = blinker in ("left", "both")
  car.rightBlinker = blinker in ("right", "both")
  car.gasPressed = gas
  sm["carControl"].longActive = long_active
  sm["selfdriveState"].experimentalMode = e2e
  sm["modelV2"].action.desiredAcceleration = 0.6
  sm["modelV2"].action.shouldStop = False
  speeds, rates = _model(V_EGO, yaw)
  sm["modelV2"].velocity.x = speeds
  sm["modelV2"].orientationRate.z = rates
  return turn_signal_ceiling(sm, cp, sm["carState"].vCruise / 3.6, enabled=enabled)


def test_ceiling_requires_one_blinker_drive_long_and_no_gas():
  cp = CarInterface.get_non_essential_params(CAR.HONDA_CIVIC)
  assert _scene(cp, blinker="off", yaw=TIGHT_YAW) is None
  assert _scene(cp, blinker="both") is None
  assert _scene(cp, gas=True) is None
  assert _scene(cp, gear="park") is None
  assert _scene(cp, long_active=False) is None
  assert _scene(cp, enabled=False) is None
  # Straight predicted path: the formula is above cruise, so speed is not raised.
  assert _scene(cp, yaw=0.0) is None
  assert _scene(cp, blinker="left") == pytest.approx(EXPECTED_CAP)
  assert _scene(cp, blinker="right") == pytest.approx(EXPECTED_CAP)


def _plan(cp, **scene):
  planner = LongitudinalPlanner(cp, init_v=V_EGO)
  for _ in range(FRAMES):
    sm, _ = messages(e2e=scene.get("e2e", False))
    car = sm["carState"]
    car.vEgo = V_EGO
    car.gearShifter = scene.get("gear", "drive")
    blinker = scene.get("blinker", "off")
    car.leftBlinker = blinker in ("left", "both")
    car.rightBlinker = blinker in ("right", "both")
    car.gasPressed = scene.get("gas", False)
    sm["carControl"].longActive = scene.get("long_active", True)
    e2e = scene.get("e2e", False)
    sm["selfdriveState"].experimentalMode = e2e
    sm["modelV2"].action.desiredAcceleration = 0.6
    sm["modelV2"].action.shouldStop = False
    speeds, rates = _model(V_EGO, scene.get("yaw", 0.0))
    sm["modelV2"].velocity.x = speeds
    sm["modelV2"].orientationRate.z = rates
    planner.update(sm, turn_signal_slowdown=scene.get("enabled", True))
  return float(planner.output_a_target), float(planner.a_cruise)


@pytest.mark.parametrize("e2e", [False, True])
def test_tight_curve_slows_chill_and_experimental_without_raising_speed_or_braking_harder(e2e):
  cp = CarInterface.get_non_essential_params(CAR.HONDA_CIVIC)
  baseline = _plan(cp, e2e=e2e, blinker="off", yaw=TIGHT_YAW)
  straight = _plan(cp, e2e=e2e, blinker="left", yaw=0.0)
  capped = _plan(cp, e2e=e2e, blinker="left", yaw=TIGHT_YAW)
  disabled = _plan(cp, e2e=e2e, blinker="left", yaw=TIGHT_YAW, enabled=False)
  both = _plan(cp, e2e=e2e, blinker="both", yaw=TIGHT_YAW)
  gas = _plan(cp, e2e=e2e, blinker="left", yaw=TIGHT_YAW, gas=True)
  parked = _plan(cp, e2e=e2e, blinker="left", yaw=TIGHT_YAW, gear="park")
  inactive = _plan(cp, e2e=e2e, blinker="left", yaw=TIGHT_YAW, long_active=False)

  assert straight == pytest.approx(baseline)
  assert disabled == pytest.approx(baseline)
  assert both == pytest.approx(baseline)
  assert capped[0] < baseline[0]
  assert capped[0] <= baseline[0]
  assert capped[1] >= A_CRUISE_MIN - 1e-6
  assert capped[0] >= A_CRUISE_MIN - 1e-6
  # Gas, park, and inactive long each keep their own plan; the cap does not change it.
  own_gas = _plan(cp, e2e=e2e, blinker="off", yaw=TIGHT_YAW, gas=True)
  own_park = _plan(cp, e2e=e2e, blinker="off", yaw=TIGHT_YAW, gear="park")
  own_inactive = _plan(cp, e2e=e2e, blinker="off", yaw=TIGHT_YAW, long_active=False)
  assert gas == pytest.approx(own_gas)
  assert parked == pytest.approx(own_park)
  assert inactive == pytest.approx(own_inactive)


class _MissingKey:
  def check_key(self, key):
    raise UnknownKeyName(key)

  def get_param_path(self, key):
    raise UnknownKeyName(key)


def test_missing_param_defaults_on_and_fallback_file_switches_off(tmp_path):
  params = _MissingKey()
  assert read_enabled(params, root=tmp_path) == (True, None, True)
  assert write_enabled(params, False, expected=None, root=tmp_path)
  assert read_enabled(params, root=tmp_path) == (False, b"0", True)
  assert (tmp_path / KEY).read_bytes() == b"0"
  prefs = TurnSignalPreferences(params, root=tmp_path)
  assert prefs.sample(0) is False
  assert write_enabled(params, True, expected=b"0", root=tmp_path)
  assert prefs.sample(2_000_000_000) is True


def test_registered_param_round_trip(tmp_path):
  from openpilot.common.params import Params

  params = Params(str(tmp_path))
  enabled, raw, valid = read_enabled(params, root=tmp_path / "unused")
  assert (enabled, raw, valid) == (True, None, True)
  assert write_enabled(params, False, expected=None, root=tmp_path / "unused")
  assert params.get_bool(KEY) is False
  assert not (tmp_path / "unused" / KEY).exists()
  prefs = TurnSignalPreferences(params, root=tmp_path / "unused")
  assert prefs.sample(0) is False
  assert Path(params.get_param_path(KEY)).read_bytes() == b"0"
