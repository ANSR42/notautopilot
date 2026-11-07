"""Locks the offline route-intent timing map to live source constants.

No msgq, no model run, and no steering change. Desire here is an intent input,
not a completed turn.
"""

from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pytest

from cereal import log

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
  DesireHelper,
)
from openpilot.selfdrive.controls.tests.route_turn_timing_map import (
  DEFAULT_APPROACH_SPEEDS_M_S,
  SYNTHETIC_LEFT_ARC_RADIUS_M,
  build_timing_map,
)
from openpilot.selfdrive.controls.tests.wide_turn_stage_harness import tesla_min_radius_m
from openpilot.selfdrive.modeld.constants import ModelConstants
from opendbc.car.tesla.values import CarControllerParams


def _source(relative: str) -> str:
  return Path(__file__).resolve().parents[3].joinpath(relative).read_text(encoding="utf-8")


def _toggles():
  return SimpleNamespace(
    lane_changes=True, lane_change_delay=0.0, lane_detection_width=3.0, minimum_lane_change_speed=20.0,
    nudgeless=False, nudgeless_lane_change_only_when_engaged=False, one_lane_change=False,
    use_turn_desires=False, lane_changes_require_cruise=False, lane_change_time_max=10.0,
    nav_desires_allowed=True, nav_lane_positioning_allowed=True,
  )


def _car(speed):
  return SimpleNamespace(
    vEgo=speed, leftBlinker=True, rightBlinker=False, leftBlindspot=False, rightBlindspot=False,
    steeringPressed=False, steeringTorque=0.0, standstill=False,
    cruiseState=SimpleNamespace(enabled=True),
  )


def _route_desire(speed):
  # 20 m is inside the preview window at every grid speed. At 5 m/s that window
  # is the 35 m minimum, so a farther instruction is not imminent yet.
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": "turn",
    "maneuverModifier": "left",
    "maneuverDistance": 20.0,
    "updatedAtMonotonic": monotonic(),
  }
  helper.update(
    _car(speed), True, 0.0,
    SimpleNamespace(laneWidthLeft=4.0, laneWidthRight=4.0, redLight=False, forcingStop=False, stopSignConfirmed=False),
    _toggles(),
  )
  return helper.desire


def test_map_reads_live_constants_and_does_not_publish():
  text = _source("selfdrive/controls/tests/route_turn_timing_map.py")
  assert "import messaging" not in text
  assert "msgq" not in text
  assert "PubMaster" not in text
  assert "nav_longitudinal_allowed =" not in text
  for relative in (
    "selfdrive/controls/controlsd.py",
    "selfdrive/controls/lib/desire_helper.py",
    "selfdrive/controls/lib/lane_centering.py",
    "opendbc/car/tesla/values.py",
  ):
    assert "route_turn_timing_map" not in _source(relative)

  report = build_timing_map()
  assert tuple(row.speed_m_s for row in report.rows) == DEFAULT_APPROACH_SPEEDS_M_S
  assert report.nav_turn_max_speed_m_s == NAV_TURN_MAX_SPEED
  assert report.turn_lead_min_m_s == 3.0
  assert report.turn_lead_max_m_s == 7.0
  assert report.arc_radius_m == SYNTHETIC_LEFT_ARC_RADIUS_M == 20.0


def test_preview_and_signal_distances_match_desire_helper():
  report = build_timing_map()
  for row in report.rows:
    car = _car(row.speed_m_s)
    state = {
      "valid": True,
      "maneuverType": "turn",
      "maneuverModifier": "left",
      "maneuverDistance": row.signal_lead_distance_m,
    }
    assert DesireHelper._nav_turn_is_imminent(car, row.preview_distance_m)
    assert not DesireHelper._nav_turn_is_imminent(car, row.preview_distance_m + 0.05)
    assert DesireHelper._nav_turn_signal_matches(car, state)
    beyond = dict(state, maneuverDistance=row.signal_lead_distance_m + 0.05)
    assert not DesireHelper._nav_turn_signal_matches(car, beyond)

    raw_preview = max(row.speed_m_s, 0.0) * NAV_TURN_PREVIEW_SECONDS
    assert NAV_TURN_MIN_DISTANCE <= row.preview_distance_m <= NAV_TURN_MAX_DISTANCE
    if NAV_TURN_MIN_DISTANCE <= raw_preview <= NAV_TURN_MAX_DISTANCE:
      assert row.preview_distance_m == pytest.approx(raw_preview)
    raw_signal = NAV_TURN_SIGNAL_BASE_DISTANCE + row.speed_m_s * NAV_TURN_SIGNAL_LEAD_TIME
    assert NAV_TURN_SIGNAL_MIN_DISTANCE <= row.signal_lead_distance_m <= NAV_TURN_SIGNAL_MAX_DISTANCE
    if NAV_TURN_SIGNAL_MIN_DISTANCE <= raw_signal <= NAV_TURN_SIGNAL_MAX_DISTANCE:
      assert row.signal_lead_distance_m == pytest.approx(raw_signal)


def test_speed_gates_and_the_desire_without_lead_gap():
  report = build_timing_map()
  fast = report.row_at(13.9)
  slow = report.row_at(5.0)
  capped = report.row_at(14.0)
  at_lead_end = report.row_at(7.0)

  assert fast.desire_possible and not fast.turn_lead_active and fast.desire_without_turn_lead
  assert fast.tesla_cap_widens_arc
  assert fast.tesla_min_radius_m == pytest.approx(tesla_min_radius_m(13.9))
  assert fast.tesla_min_radius_m > fast.arc_radius_m
  assert _route_desire(13.9) == log.Desire.turnLeft

  assert slow.desire_possible and slow.turn_lead_active and not slow.desire_without_turn_lead
  assert not slow.tesla_cap_widens_arc
  assert slow.tesla_min_radius_m < slow.arc_radius_m
  assert _route_desire(5.0) == log.Desire.turnLeft

  assert not capped.desire_possible and not capped.turn_lead_active
  assert not capped.desire_without_turn_lead
  assert _route_desire(14.0) == log.Desire.none

  assert at_lead_end.desire_possible and not at_lead_end.turn_lead_active
  assert at_lead_end.desire_without_turn_lead

  gap = [row.speed_m_s for row in report.rows if row.desire_without_turn_lead]
  assert gap == [7.0, 8.0, 10.0, 12.0, 13.9]
  for row in report.rows:
    assert row.desire_without_turn_lead is (row.desire_possible and not row.turn_lead_active)
    assert row.tesla_min_radius_m == pytest.approx(
      row.speed_m_s ** 2 / CarControllerParams.ANGLE_LIMITS.MAX_LATERAL_ACCEL
    )


def test_nav_left_and_right_targets_are_14_mph_and_stay_gated():
  report = build_timing_map()
  vcruise = _source("starpilot/controls/lib/starpilot_vcruise.py")
  assert '"left": 14.0 * CV.MPH_TO_MS' in vcruise
  assert '"right": 14.0 * CV.MPH_TO_MS' in vcruise
  for row in report.rows:
    assert row.nav_left_target_mph == 14.0
    assert row.nav_right_target_mph == 14.0
    assert row.nav_longitudinal_allowed_required
    assert row.nav_left_target_m_s == pytest.approx(14.0 * CV.MPH_TO_MS)
    assert row.nav_right_target_m_s == row.nav_left_target_m_s
    assert report.turn_lead_min_m_s <= row.nav_left_target_m_s < report.turn_lead_max_m_s
    assert row.nav_left_target_m_s < NAV_TURN_MAX_SPEED


def test_turn_desire_reaches_the_model_as_an_input_one_hot():
  """Source trace only. modeld is not started, and no artifact is loaded."""
  modeld = _source("selfdrive/modeld/modeld.py")
  helper = _source("selfdrive/controls/lib/desire_helper.py")
  assert "from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper" in modeld
  assert "DH = DesireHelper()" in modeld
  assert "desire = DH.desire" in modeld
  assert "vec_desire[desire] = 1" in modeld
  assert "DH.update(" in modeld
  assert "starpilotModelV2.turnDirection = DH.turn_direction" in modeld
  assert "inputs[self.desire_key][0] = 0" in modeld
  assert 'self.npy["desire"]' in modeld
  assert "self.desire = nav_desire" in helper
  assert "self.turn_direction = nav_desire" in helper
  assert "0.0 <= carstate.vEgo < NAV_TURN_MAX_SPEED" in helper

  assert int(log.Desire.turnLeft) == 1
  assert int(log.Desire.turnRight) == 2
  assert int(log.Desire.turnRight) < ModelConstants.DESIRE_LEN
  assert "desire @17 :Desire" in _source("cereal/log.capnp")
  assert "turnDirection @0 :TurnDirection" in _source("cereal/custom.capnp")
  assert "meta.desireState = net_output_data['desire_state']" in _source("selfdrive/modeld/fill_model_msg.py")
  # LateralPlan.desire is declared and not assigned by a publisher in this tree.
  assert "lateralPlan.desire" not in modeld
  assert ".desire =" not in _source("selfdrive/controls/controlsd.py")
