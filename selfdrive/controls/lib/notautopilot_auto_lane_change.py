"""Blinker lane change for NOTAUTOPILOT.

The behavior this module adds is the driver blinker, without a steering nudge.
It is off unless AutoLaneChange is enabled. It is not an automatic pass of
slower traffic and it does not follow a navigation instruction.

Credits for the blinker-without-nudge idea, the brake latch, and the held-blinker
repeat block: rav4kumar and Jason Wen (sunnyhaibin), sunnypilot pull request 653,
merged commit e0bb92545ceab3e3897613313b1c2adcf5e1fd51.
https://github.com/sunnypilot/sunnypilot/pull/653

That pull request's controller is not copied here. Its repository LICENSE.md at
that commit is a custom license requiring permission for commercial or closed
use and this acknowledgment: "This project uses software from Haibin Wen and
SUNNYPILOT LLC and is licensed under a custom license requiring permission for
use." The speed gate in that commit is 20 mph (v_ego < 20 * MPH_TO_MS). The
threshold below is Mike's requested strict above 25 mph. A false blind-spot
boolean is not treated as clear.

This project uses the design from Haibin Wen and SUNNYPILOT LLC. The sunnypilot
license requires permission for commercial or closed-source use.
"""

from dataclasses import dataclass

from cereal import log

from openpilot.common.constants import CV

LaneChangeDirection = log.LaneChangeDirection

# Mike's requested gate. sunnypilot PR 653 uses 20 mph, not 25.
AUTO_LANE_CHANGE_MIN_SPEED_MPH = 25.0
AUTO_LANE_CHANGE_MIN_SPEED_MS = AUTO_LANE_CHANGE_MIN_SPEED_MPH * CV.MPH_TO_MS

# DAS_status blind-spot enum in tesla_model3_party.dbc.
BSM_NO_WARNING = 0
BSM_WARNING_LEVEL_1 = 1
BSM_WARNING_LEVEL_2 = 2
BSM_SNA = 3
BSM_UNSAMPLED = 255

# Age cap before a measured period exists. A learned period tightens this to
# three periods, and never lets a sample older than this cap count as fresh.
BSM_FRESH_MAX_S = 1.0


@dataclass(frozen=True)
class BlindSpotSample:
  left_raw: int = BSM_UNSAMPLED
  right_raw: int = BSM_UNSAMPLED
  left_fresh: bool = False
  right_fresh: bool = False


def blind_spot_message_is_fresh(timestamps, now_nanos: int) -> bool:
  """True only for an accepted frame that is not missing, future, or stale."""
  if not timestamps or now_nanos <= 0:
    return False
  age_s = (now_nanos - timestamps[-1]) * 1e-9
  if age_s < 0:
    return False
  limit_s = BSM_FRESH_MAX_S
  if len(timestamps) >= 3:
    span_s = (timestamps[-1] - timestamps[0]) * 1e-9
    periods = len(timestamps) - 1
    if span_s > 0 and periods > 0:
      limit_s = min(BSM_FRESH_MAX_S, max(0.2, 3.0 * span_s / periods))
  return age_s <= limit_s


def side_is_verified_clear(sample: BlindSpotSample | None, direction: int) -> bool:
  """Fresh NO_WARNING only. Missing, stale, SNA, and warnings are not clear."""
  if sample is None:
    return False
  if direction == LaneChangeDirection.left:
    raw, fresh = sample.left_raw, sample.left_fresh
  elif direction == LaneChangeDirection.right:
    raw, fresh = sample.right_raw, sample.right_fresh
  else:
    return False
  return bool(fresh) and int(raw) == BSM_NO_WARNING


def auto_lane_change_allowed(
  *,
  enabled: bool,
  v_ego: float,
  minimum_lane_change_speed: float,
  one_blinker: bool,
  direction: int,
  blind_spot: BlindSpotSample | None,
  lane_width: float,
  minimum_lane_width: float,
  brake_latched: bool,
  repeat_blocked: bool,
  car_state_valid: bool,
) -> bool:
  if not enabled or not one_blinker or not car_state_valid or brake_latched or repeat_blocked:
    return False
  if direction not in (LaneChangeDirection.left, LaneChangeDirection.right):
    return False
  # Strictly above 25 mph, and still at or above the existing lane-change floor.
  if not (v_ego > AUTO_LANE_CHANGE_MIN_SPEED_MS and v_ego >= minimum_lane_change_speed):
    return False
  if lane_width < minimum_lane_width:
    return False
  return side_is_verified_clear(blind_spot, direction)
