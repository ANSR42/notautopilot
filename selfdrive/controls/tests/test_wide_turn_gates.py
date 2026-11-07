"""Measured gates on the path from a route turn to a Tesla steering command.

These checks use the current functions and constants. They do not select a
lane-centering floor, do not replay a log, and do not show that a car completed
a turn.
"""

import re
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import numpy as np

from cereal import log

from openpilot.common.constants import CV
from openpilot.selfdrive.controls.lib.desire_helper import NAV_TURN_MAX_SPEED, DesireHelper
from openpilot.selfdrive.controls.lib.lane_centering import LaneCenteringController
from opendbc.car.tesla.values import CarControllerParams


def _source(relative: str) -> str:
  return Path(__file__).resolve().parents[3].joinpath(relative).read_text(encoding="utf-8")


def _controlsd_constant(name: str) -> float:
  # controlsd imports the device messaging extension, which is not built here.
  match = re.search(rf"^{name} = ([0-9.]+)", _source("selfdrive/controls/controlsd.py"), re.M)
  assert match is not None
  return float(match.group(1))


def _nav_turn_target_mps(modifier: str) -> float:
  # starpilot_vcruise imports the same unbuilt messaging extension.
  text = _source("starpilot/controls/lib/starpilot_vcruise.py")
  match = re.search(rf'"{modifier}": ([0-9.]+) \* CV\.MPH_TO_MS', text)
  assert match is not None
  return float(match.group(1)) * CV.MPH_TO_MS


_XS = np.linspace(0.0, 50.0, 52)


def _path(y):
  return SimpleNamespace(x=_XS.copy(), y=np.full_like(_XS, float(y)), yStd=np.full_like(_XS, 0.1))


def _model(model_y):
  return SimpleNamespace(
    laneLines=[_path(0.0), _path(-1.8), _path(1.8), _path(0.0)],
    laneLineProbs=[0.0, 0.9, 0.9, 0.0],
    laneLineStds=[0.0, 0.1, 0.1, 0.1],
    position=_path(model_y),
    meta=SimpleNamespace(laneChangeState=log.LaneChangeState.off),
  )


def _min_radius(speed):
  return speed ** 2 / CarControllerParams.ANGLE_LIMITS.MAX_LATERAL_ACCEL


def test_route_turn_desire_is_allowed_above_the_turn_lead_speed():
  speed = NAV_TURN_MAX_SPEED - 0.1
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": "turn",
    "maneuverModifier": "left",
    "maneuverDistance": 40.0,
    "updatedAtMonotonic": monotonic(),
  }
  helper.update(
    SimpleNamespace(
      vEgo=speed, leftBlinker=True, rightBlinker=False, leftBlindspot=False, rightBlindspot=False,
      steeringPressed=False, steeringTorque=0.0, standstill=False,
      cruiseState=SimpleNamespace(enabled=True),
    ),
    True, 0.0, SimpleNamespace(laneWidthLeft=4.0, laneWidthRight=4.0, redLight=False, forcingStop=False, stopSignConfirmed=False),
    SimpleNamespace(
      lane_changes=True, lane_change_delay=0.0, lane_detection_width=3.0, minimum_lane_change_speed=20.0,
      nudgeless=False, nudgeless_lane_change_only_when_engaged=False, one_lane_change=False,
      use_turn_desires=False, lane_changes_require_cruise=False, lane_change_time_max=10.0,
      nav_desires_allowed=True, nav_lane_positioning_allowed=True,
    ),
  )

  assert helper.desire == log.Desire.turnLeft
  lead_min = _controlsd_constant("TURN_LEAD_MIN_SPEED")
  lead_max = _controlsd_constant("TURN_LEAD_MAX_SPEED")
  assert speed >= lead_max
  assert not (lead_min <= speed < lead_max)
  assert 'return brand != "rivian" or lateral_control_mode != LateralControlMode.angle' in _source("selfdrive/controls/controlsd.py")


def test_tesla_lateral_accel_cap_is_wider_at_the_route_desire_speed_than_at_the_cruise_target():
  desire_speed = NAV_TURN_MAX_SPEED - 0.1
  cruise_speed = _nav_turn_target_mps("left")
  assert cruise_speed < desire_speed
  assert _min_radius(desire_speed) > _min_radius(cruise_speed)
  assert _min_radius(desire_speed) > 40.0


def test_lane_centering_can_oppose_a_leftward_path_until_the_blinker_releases_it():
  controller = LaneCenteringController()
  model = _model(-0.8)
  output = 0.0
  for _ in range(400):
    output = controller.update(0.0, model, 12.0, True, 0.0, 0.0, True, True, False, False, False)
  assert output > 0.0
  assert output <= 0.0012

  for _ in range(400):
    output = controller.update(0.0, model, 12.0, True, 0.0, 0.0, True, True, True, True, False)
  assert abs(output) < 1e-4
