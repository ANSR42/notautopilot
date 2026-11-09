"""Offline checks for the sunnypilot blinker timer on NudgelessLaneChange.

These tests do not drive a car and do not treat a false blind-spot boolean
as a measured clear lane.
"""

from types import SimpleNamespace

from cereal import log

from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper
from openpilot.selfdrive.controls.lib.notautopilot_auto_lane_change import (
  USER_MIN_SPEED_MPH,
  BlinkerLaneChange,
)

LaneChangeState = log.LaneChangeState


def _toggles(**overrides):
  values = dict(
    lane_changes=True, lane_change_delay=0.0, lane_detection_width=3.0,
    minimum_lane_change_speed=20.0 * CV.MPH_TO_MS,
    nudgeless=False, nudgeless_lane_change_only_when_engaged=False, nudgeless_bsm_delay=False,
    one_lane_change=False, use_turn_desires=False, lane_changes_require_cruise=False,
    lane_change_time_max=10.0, nav_desires_allowed=False, nav_lane_positioning_allowed=False,
  )
  values.update(overrides)
  return SimpleNamespace(**values)


def _plan(width=4.0):
  return SimpleNamespace(
    laneWidthLeft=width, laneWidthRight=width, redLight=False, forcingStop=False, stopSignConfirmed=False,
  )


def _car(**overrides):
  values = dict(
    vEgo=30.0 * CV.MPH_TO_MS, leftBlinker=True, rightBlinker=False,
    leftBlindspot=False, rightBlindspot=False, steeringPressed=False, steeringTorque=0.0,
    standstill=False, brakePressed=False, canValid=True,
    cruiseState=SimpleNamespace(enabled=True),
  )
  values.update(overrides)
  return SimpleNamespace(**values)


def _run(helper, frames, toggles, **car):
  sample = _car(**car)
  for _ in range(frames):
    helper.update(sample, True, 0.0, _plan(), toggles, True)
  return helper


def test_settings_keep_one_nudgeless_toggle_and_default_off():
  header = open("common/params_keys.h", encoding="utf-8").read()
  assert '{"NudgelessLaneChange", {PERSISTENT, BOOL, "0", "0", 0, SETTINGS_SIMPLE}}' in header
  assert '{"NudgelessLaneChangeBsmDelay", {PERSISTENT, BOOL, "0", "0", 1, SETTINGS_SIMPLE}}' in header
  assert "AutoLaneChange" not in header
  layout = open("selfdrive/ui/layouts/settings/starpilot/lateral.py", encoding="utf-8").read()
  assert layout.count('tr_noop("Auto Lane Changes")') == 1
  assert 'tr_noop("Delay with Blind Spot")' in layout
  variables = open("starpilot/common/starpilot_variables.py", encoding="utf-8").read()
  assert 'toggle.nudgeless = self.get_value("NudgelessLaneChange"' in variables
  assert 'toggle.nudgeless_bsm_delay = self.get_value("NudgelessLaneChangeBsmDelay"' in variables
  assert "auto_lane_change" not in variables


def test_upstream_timer_brake_latch_and_blindspot_delay():
  idle = BlinkerLaneChange()
  idle.update(nudgeless=False, delay_s=0.0, bsm_delay=False, blindspot_detected=False, brake_pressed=False)
  assert idle.allowed is False

  quick = BlinkerLaneChange()
  quick.update(nudgeless=True, delay_s=0.05, bsm_delay=False, blindspot_detected=False, brake_pressed=False)
  assert quick.wait_timer == DT_MDL
  assert quick.allowed is False
  quick.update(nudgeless=True, delay_s=0.05, bsm_delay=False, blindspot_detected=False, brake_pressed=False)
  assert quick.allowed is True

  blocked = BlinkerLaneChange()
  for _ in range(30):
    blocked.update(nudgeless=True, delay_s=0.05, bsm_delay=True, blindspot_detected=True, brake_pressed=False)
  assert blocked.allowed is False
  assert blocked.wait_timer == -1.0
  blocked.update(nudgeless=True, delay_s=0.05, bsm_delay=True, blindspot_detected=False, brake_pressed=False)
  assert blocked.allowed is False

  braked = BlinkerLaneChange()
  braked.update(nudgeless=True, delay_s=0.0, bsm_delay=False, blindspot_detected=False, brake_pressed=True)
  braked.update(nudgeless=True, delay_s=0.0, bsm_delay=False, blindspot_detected=False, brake_pressed=False)
  assert braked.allowed is False
  braked.note_state(lane_change_off=True, lane_change_starting=False)
  braked.update(nudgeless=True, delay_s=0.0, bsm_delay=False, blindspot_detected=False, brake_pressed=False)
  assert braked.allowed is True


def test_nudgeless_off_still_needs_a_nudge_and_on_waits_out_the_delay():
  off = DesireHelper()
  _run(off, 5, _toggles(nudgeless=False, lane_change_delay=0.0))
  assert off.lane_change_state == LaneChangeState.preLaneChange
  off.update(_car(steeringPressed=True, steeringTorque=1.0), True, 0.0, _plan(), _toggles(nudgeless=False), True)
  assert off.lane_change_state == LaneChangeState.laneChangeStarting

  waiting = DesireHelper()
  toggles = _toggles(nudgeless=True, lane_change_delay=0.05)
  _run(waiting, 2, toggles)
  assert waiting.lane_change_state == LaneChangeState.preLaneChange
  waiting.update(_car(), True, 0.0, _plan(), toggles, True)
  assert waiting.lane_change_state == LaneChangeState.laneChangeStarting


def test_user_speed_gate_is_above_25_mph_and_upstream_floor_stays_for_nudges():
  assert USER_MIN_SPEED_MPH == 25.0
  source = open("selfdrive/controls/lib/notautopilot_auto_lane_change.py", encoding="utf-8").read()
  assert "20 mph" in source
  exact = DesireHelper()
  toggles = _toggles(nudgeless=True, lane_change_delay=0.0)
  _run(exact, 4, toggles, vEgo=25.0 * CV.MPH_TO_MS)
  assert exact.lane_change_state == LaneChangeState.preLaneChange

  above = DesireHelper()
  _run(above, 3, toggles, vEgo=25.0 * CV.MPH_TO_MS + 1e-4)
  assert above.lane_change_state == LaneChangeState.laneChangeStarting

  nudged = DesireHelper()
  slow = _car(vEgo=22.0 * CV.MPH_TO_MS, steeringPressed=True, steeringTorque=1.0)
  nudged.update(slow, True, 0.0, _plan(), _toggles(nudgeless=False), True)
  nudged.update(slow, True, 0.0, _plan(), _toggles(nudgeless=False), True)
  assert nudged.lane_change_state == LaneChangeState.laneChangeStarting


def test_blindspot_bool_blocks_start_and_delay_restarts_the_timer():
  occupied = DesireHelper()
  toggles = _toggles(nudgeless=True, lane_change_delay=0.0)
  _run(occupied, 4, toggles, leftBlindspot=True)
  assert occupied.lane_change_state == LaneChangeState.preLaneChange

  restart = DesireHelper()
  delayed = _toggles(nudgeless=True, lane_change_delay=1.0, nudgeless_bsm_delay=True)
  _run(restart, 40, delayed, leftBlindspot=True)
  restart.update(_car(leftBlindspot=False), True, 0.0, _plan(), delayed, True)
  assert restart.lane_change_state == LaneChangeState.preLaneChange
  assert restart.blinker_lane_change.wait_timer < 1.0


def test_brake_direction_and_held_blinker():
  brake = DesireHelper()
  toggles = _toggles(nudgeless=True, lane_change_delay=0.0)
  _run(brake, 3, toggles, brakePressed=True)
  assert brake.lane_change_state == LaneChangeState.preLaneChange
  brake.update(_car(brakePressed=False), True, 0.0, _plan(), toggles, True)
  assert brake.lane_change_state == LaneChangeState.preLaneChange

  both = DesireHelper()
  _run(both, 3, toggles, rightBlinker=True)
  assert both.lane_change_state == LaneChangeState.off

  held = DesireHelper()
  _run(held, 3, toggles)
  assert held.lane_change_state == LaneChangeState.laneChangeStarting
  car = _car()
  for _ in range(80):
    held.update(car, True, 0.0, _plan(), toggles, True)
  assert held.lane_change_state == LaneChangeState.preLaneChange
  assert held.blinker_lane_change.prev_lane_change is True
  held.update(car, True, 0.0, _plan(), toggles, True)
  assert held.lane_change_state == LaneChangeState.preLaneChange


def test_disengage_resets_and_a_later_warning_does_not_abort():
  helper = DesireHelper()
  toggles = _toggles(nudgeless=True, lane_change_delay=0.0)
  _run(helper, 3, toggles)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting
  helper.update(_car(leftBlindspot=True), True, 0.5, _plan(), toggles, True)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting
  helper.update(_car(), False, 0.5, _plan(), toggles, False)
  assert helper.lane_change_state == LaneChangeState.off
  assert helper.blinker_lane_change.prev_brake_pressed is False
