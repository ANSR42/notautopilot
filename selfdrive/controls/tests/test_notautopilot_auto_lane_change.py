"""Default-off blinker lane change. These tests do not drive a car."""

from types import SimpleNamespace

from cereal import log

from openpilot.common.constants import CV
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper
from openpilot.selfdrive.controls.lib.notautopilot_auto_lane_change import (
  AUTO_LANE_CHANGE_MIN_SPEED_MS,
  BSM_NO_WARNING,
  BSM_SNA,
  BSM_UNSAMPLED,
  BSM_WARNING_LEVEL_1,
  BlindSpotSample,
  auto_lane_change_allowed,
  blind_spot_message_is_fresh,
  side_is_verified_clear,
)

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection


def _toggles(**overrides):
  values = dict(
    lane_changes=True, lane_change_delay=0.0, lane_detection_width=3.0, minimum_lane_change_speed=20.0 * CV.MPH_TO_MS,
    nudgeless=False, nudgeless_lane_change_only_when_engaged=False, one_lane_change=False,
    use_turn_desires=False, lane_changes_require_cruise=False, lane_change_time_max=10.0,
    nav_desires_allowed=False, nav_lane_positioning_allowed=False, auto_lane_change=False,
  )
  values.update(overrides)
  return SimpleNamespace(**values)


def _plan(width=4.0):
  return SimpleNamespace(
    laneWidthLeft=width, laneWidthRight=width, redLight=False, forcingStop=False, stopSignConfirmed=False,
  )


def _car(**overrides):
  values = dict(
    vEgo=30.0 * CV.MPH_TO_MS, leftBlinker=True, rightBlinker=False, leftBlindspot=False, rightBlindspot=False,
    steeringPressed=False, steeringTorque=0.0, standstill=False, brakePressed=False, canValid=True,
    cruiseState=SimpleNamespace(enabled=True),
  )
  values.update(overrides)
  return SimpleNamespace(**values)


def _clear():
  return BlindSpotSample(left_raw=BSM_NO_WARNING, right_raw=BSM_NO_WARNING, left_fresh=True, right_fresh=True)


def _step(helper, car, toggles, blind_spot, frames=2):
  for _ in range(frames):
    helper.update(car, True, 0.0, _plan(), toggles, True, blind_spot)
  return helper


def test_param_and_settings_label_default_off():
  header = open("common/params_keys.h", encoding="utf-8").read()
  assert '{"AutoLaneChange", {PERSISTENT, BOOL, "0", "0", 0, SETTINGS_SIMPLE}}' in header
  layout = open("selfdrive/ui/layouts/settings/starpilot/lateral.py", encoding="utf-8").read()
  assert 'tr_noop("Auto Lane Change")' in layout
  variables = open("starpilot/common/starpilot_variables.py", encoding="utf-8").read()
  assert 'toggle.auto_lane_change = self.get_value("AutoLaneChange", condition=toggle.lane_changes)' in variables
  assert "AutoLaneChange" in open("starpilot/common/safe_mode.py", encoding="utf-8").read()


def test_missing_stale_sna_and_warning_are_not_clear():
  assert side_is_verified_clear(None, LaneChangeDirection.left) is False
  assert side_is_verified_clear(BlindSpotSample(), LaneChangeDirection.left) is False
  occupied = BlindSpotSample(left_raw=BSM_WARNING_LEVEL_1, left_fresh=True, right_raw=BSM_NO_WARNING, right_fresh=True)
  assert side_is_verified_clear(occupied, LaneChangeDirection.left) is False
  assert side_is_verified_clear(occupied, LaneChangeDirection.right) is True
  sna = BlindSpotSample(left_raw=BSM_SNA, left_fresh=True)
  assert side_is_verified_clear(sna, LaneChangeDirection.left) is False
  stale = BlindSpotSample(left_raw=BSM_NO_WARNING, left_fresh=False)
  assert side_is_verified_clear(stale, LaneChangeDirection.left) is False
  assert side_is_verified_clear(
    BlindSpotSample(left_raw=BSM_UNSAMPLED, left_fresh=True), LaneChangeDirection.left,
  ) is False


def test_freshness_rejects_missing_future_and_old_frames():
  assert blind_spot_message_is_fresh([], 1_000_000_000) is False
  assert blind_spot_message_is_fresh([2_000_000_000], 1_000_000_000) is False
  assert blind_spot_message_is_fresh([0], 1_500_000_000) is False
  assert blind_spot_message_is_fresh([500_000_000], 1_000_000_000) is True
  # Three samples 100 ms apart: the cap becomes 300 ms, so 400 ms is stale.
  stamps = [0, 100_000_000, 200_000_000]
  assert blind_spot_message_is_fresh(stamps, 500_000_000) is True
  assert blind_spot_message_is_fresh(stamps, 700_000_000) is False


def test_toggle_off_still_requires_a_nudge_and_on_starts_without_one():
  off = DesireHelper()
  _step(off, _car(), _toggles(auto_lane_change=False), _clear())
  assert off.lane_change_state == LaneChangeState.preLaneChange

  nudged = DesireHelper()
  _step(nudged, _car(steeringPressed=True, steeringTorque=1.0), _toggles(), _clear())
  assert nudged.lane_change_state == LaneChangeState.laneChangeStarting

  auto = DesireHelper()
  _step(auto, _car(), _toggles(auto_lane_change=True), _clear())
  assert auto.lane_change_state == LaneChangeState.laneChangeStarting
  assert auto.desire == log.Desire.laneChangeLeft


def test_speed_is_strictly_above_25_mph_and_keeps_the_existing_floor():
  assert AUTO_LANE_CHANGE_MIN_SPEED_MS == 25.0 * CV.MPH_TO_MS
  common = dict(
    enabled=True, one_blinker=True, direction=LaneChangeDirection.left, blind_spot=_clear(),
    lane_width=4.0, minimum_lane_width=3.0, brake_latched=False, repeat_blocked=False, car_state_valid=True,
    minimum_lane_change_speed=20.0 * CV.MPH_TO_MS,
  )
  assert auto_lane_change_allowed(v_ego=25.0 * CV.MPH_TO_MS, **common) is False
  assert auto_lane_change_allowed(v_ego=25.0 * CV.MPH_TO_MS + 1e-6, **common) is True
  assert auto_lane_change_allowed(
    v_ego=30.0 * CV.MPH_TO_MS, minimum_lane_change_speed=40.0 * CV.MPH_TO_MS, **{k: v for k, v in common.items() if k != "minimum_lane_change_speed"},
  ) is False

  helper = DesireHelper()
  _step(helper, _car(vEgo=22.0 * CV.MPH_TO_MS), _toggles(auto_lane_change=True), _clear())
  assert helper.lane_change_state == LaneChangeState.preLaneChange


def test_fail_closed_samples_do_not_start_and_nudge_still_can():
  for sample in (
    None,
    BlindSpotSample(),
    BlindSpotSample(left_raw=BSM_WARNING_LEVEL_1, left_fresh=True),
    BlindSpotSample(left_raw=BSM_SNA, left_fresh=True),
    BlindSpotSample(left_raw=BSM_NO_WARNING, left_fresh=False),
  ):
    helper = DesireHelper()
    _step(helper, _car(), _toggles(auto_lane_change=True), sample)
    assert helper.lane_change_state == LaneChangeState.preLaneChange

  invalid = DesireHelper()
  _step(invalid, _car(canValid=False), _toggles(auto_lane_change=True), _clear())
  assert invalid.lane_change_state == LaneChangeState.preLaneChange

  nudged = DesireHelper()
  _step(nudged, _car(steeringPressed=True, steeringTorque=1.0, canValid=False), _toggles(auto_lane_change=True), None)
  assert nudged.lane_change_state == LaneChangeState.laneChangeStarting


def test_both_blinkers_low_speed_brake_direction_change_and_held_stalk():
  both = DesireHelper()
  _step(both, _car(rightBlinker=True), _toggles(auto_lane_change=True), _clear())
  assert both.lane_change_state == LaneChangeState.off

  slow = DesireHelper()
  _step(slow, _car(vEgo=5.0), _toggles(auto_lane_change=True, use_turn_desires=False), _clear())
  assert slow.lane_change_state == LaneChangeState.off
  assert slow.desire == log.Desire.none

  brake = DesireHelper()
  _step(brake, _car(brakePressed=True), _toggles(auto_lane_change=True), _clear())
  assert brake.lane_change_state == LaneChangeState.preLaneChange
  brake.update(_car(brakePressed=False), True, 0.0, _plan(), _toggles(auto_lane_change=True), True, _clear())
  assert brake.lane_change_state == LaneChangeState.preLaneChange

  right_blocked = BlindSpotSample(left_raw=BSM_NO_WARNING, left_fresh=True, right_raw=BSM_WARNING_LEVEL_1, right_fresh=True)
  direction = DesireHelper()
  direction.update(_car(), True, 0.0, _plan(), _toggles(auto_lane_change=True), True, right_blocked)
  direction.update(_car(leftBlinker=False, rightBlinker=True), True, 0.0, _plan(), _toggles(auto_lane_change=True), True, right_blocked)
  assert direction.lane_change_state == LaneChangeState.preLaneChange

  held = DesireHelper()
  toggles = _toggles(auto_lane_change=True)
  sample = _clear()
  car = _car()
  _step(held, car, toggles, sample)
  assert held.lane_change_state == LaneChangeState.laneChangeStarting
  for _ in range(80):
    held.update(car, True, 0.0, _plan(), toggles, True, sample)
  assert held.lane_change_state == LaneChangeState.preLaneChange
  assert held.auto_repeat_block is True
  held.update(car, True, 0.0, _plan(), toggles, True, sample)
  assert held.lane_change_state == LaneChangeState.preLaneChange


def test_disengage_and_mid_maneuver_warning_follow_the_existing_state_machine():
  helper = DesireHelper()
  toggles = _toggles(auto_lane_change=True)
  sample = _clear()
  _step(helper, _car(), toggles, sample)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting
  occupied = BlindSpotSample(left_raw=BSM_WARNING_LEVEL_1, left_fresh=True, right_raw=BSM_NO_WARNING, right_fresh=True)
  helper.update(_car(leftBlindspot=True), True, 0.5, _plan(), toggles, True, occupied)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting

  helper.update(_car(), False, 0.5, _plan(), toggles, False, sample)
  assert helper.lane_change_state == LaneChangeState.off
  assert helper.auto_repeat_block is False


def test_narrow_lane_blocks_auto_start():
  helper = DesireHelper()
  helper.update(_car(), True, 0.0, _plan(width=2.0), _toggles(auto_lane_change=True), True, _clear())
  helper.update(_car(), True, 0.0, _plan(width=2.0), _toggles(auto_lane_change=True), True, _clear())
  assert helper.lane_change_state == LaneChangeState.preLaneChange


def test_accepted_agnos_contains_measured_19_9_without_changing_the_build_pin():
  text = open("launch_env.sh", encoding="utf-8").read()
  assert 'export AGNOS_VERSION="19.8.1"' in text
  assert 'export AGNOS_ACCEPTED_VERSIONS="19.8.1 19.8.2 19.9 20.2-starpilot.1 20.2.1"' in text
