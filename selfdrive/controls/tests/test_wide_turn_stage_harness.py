"""Stage report and route-turn timing. Not a road test and not a log replay.

Timing, from selfdrive/controls/lib/desire_helper.py:
  DesireHelper._navigation_desire emits turnLeft/turnRight only while
  nav_desires_allowed, lateral control is active, NavInstructionState is valid
  and younger than NAV_INSTRUCTION_MAX_AGE, maneuverType is "turn", the modifier
  is left/sharpLeft or right/sharpRight, the matching blinker is the only one on,
  that side's blindspot is clear, speed is in [0, NAV_TURN_MAX_SPEED), the car
  is not stopped, turn_stop_hold is clear, and maneuverDistance is inside the
  preview window. DesireHelper.update copies that desire only when
  lane_change_state is off.
  A blinker also feeds LaneCenteringController.update(pause_on_signal=True),
  which is LaneCenteringPauseOnSignal. The correction then fades toward zero.
  Turn lead is controlsd.TURN_LEAD_MIN_SPEED <= v < TURN_LEAD_MAX_SPEED.
  NAV_TURN_MAX_SPEED is 14 m/s, so a typical route-turn desire speed is outside
  that window and the lead is inactive there.
"""

from time import monotonic
from types import SimpleNamespace

from cereal import log

from openpilot.selfdrive.controls.lib.desire_helper import NAV_TURN_MAX_SPEED, DesireHelper
from openpilot.selfdrive.controls.tests.wide_turn_stage_harness import (
  diagnose,
  tesla_min_radius_m,
)


def _toggles():
  return SimpleNamespace(
    lane_changes=True, lane_change_delay=0.0, lane_detection_width=3.0, minimum_lane_change_speed=20.0,
    nudgeless=False, nudgeless_lane_change_only_when_engaged=False, one_lane_change=False,
    use_turn_desires=False, lane_changes_require_cruise=False, lane_change_time_max=10.0,
    nav_desires_allowed=True, nav_lane_positioning_allowed=True,
  )


def _car(**overrides):
  state = dict(
    vEgo=8.0, leftBlinker=True, rightBlinker=False, leftBlindspot=False, rightBlindspot=False,
    steeringPressed=False, steeringTorque=0.0, standstill=False,
    cruiseState=SimpleNamespace(enabled=True),
  )
  state.update(overrides)
  return SimpleNamespace(**state)


def _plan():
  return SimpleNamespace(
    laneWidthLeft=4.0, laneWidthRight=4.0, redLight=False, forcingStop=False, stopSignConfirmed=False,
  )


def _desire(car, age_s=0.0, distance=40.0, modifier="left", maneuver_type="turn"):
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": maneuver_type,
    "maneuverModifier": modifier,
    "maneuverDistance": distance,
    "updatedAtMonotonic": monotonic() - age_s,
  }
  helper.update(car, True, 0.0, _plan(), _toggles())
  return helper.desire


def test_circle_fit_matches_the_controlsd_formula():
  from pathlib import Path
  text = Path(__file__).resolve().parents[3].joinpath("selfdrive/controls/controlsd.py").read_text(encoding="utf-8")
  assert "return 2.0 * py / d2" in text
  assert "wide_turn_stage_harness" not in text


def test_fast_route_speed_is_widened_by_the_tesla_cap_while_turn_lead_is_off():
  report = diagnose(13.9, radius_m=20.0, blinker=True)
  assert report.model_curvature_1_per_m == pytest_approx(-0.05)
  assert report.lane_centering_opposes_model
  assert report.lane_centering_before_pause_1_per_m > 0.0
  assert abs(report.lane_centering_after_pause_1_per_m) < 1e-3
  assert not report.turn_lead_active
  assert report.turn_lead_max_m_s == 7.0
  assert report.turn_lead_min_m_s == 3.0
  assert report.requested_curvature_1_per_m < 0.0
  assert report.tesla_cap_widens_radius
  assert report.tesla_limited_radius_m == pytest_approx(tesla_min_radius_m(13.9))
  assert report.tesla_min_radius_m > report.model_radius_m


def test_inside_the_lead_window_the_same_arc_is_not_widened_by_the_tesla_cap():
  report = diagnose(5.0, radius_m=20.0, blinker=False)
  assert report.turn_lead_active
  assert report.lane_centering_opposes_model
  assert not report.tesla_cap_widens_radius
  assert report.requested_radius_m > report.model_radius_m
  assert report.tesla_limited_radius_m == pytest_approx(report.requested_radius_m)
  assert report.requested_curvature_without_pause_1_per_m > report.model_curvature_1_per_m


def test_route_turn_timing_creates_and_clears_the_desire():
  assert _desire(_car(vEgo=8.0)) == log.Desire.turnLeft
  assert _desire(_car(vEgo=NAV_TURN_MAX_SPEED)) == log.Desire.none
  assert _desire(_car(vEgo=8.0, leftBlinker=False)) == log.Desire.none
  assert _desire(_car(vEgo=8.0, leftBlindspot=True)) == log.Desire.none
  assert _desire(_car(vEgo=8.0), age_s=10.0) == log.Desire.none
  fast = diagnose(NAV_TURN_MAX_SPEED - 0.05)
  assert not fast.turn_lead_active


def pytest_approx(value):
  import pytest
  return pytest.approx(value, rel=0.02, abs=1e-4)
