"""Blinker lane change using the existing NudgelessLaneChange setting.

This follows sunnypilot pull request 653, merged as
e0bb92545ceab3e3897613313b1c2adcf5e1fd51, by rav4kumar with later commits by
Jason Wen (sunnyhaibin):
https://github.com/sunnypilot/sunnypilot/pull/653

The upstream controller is not copied. Its timer, blind-spot delay, brake
latch, and one-change-per-blinker block are implemented here against the
settings this tree already has. NudgelessLaneChange off matches upstream's
default Nudge mode: the blinker does not start a lane change. NudgelessLaneChange
on uses the existing Lane Change Delay slider. Upstream's nudgeless preset is
0.05 seconds and its named presets are 0.5, 1, 2, and 3 seconds. This slider
already defaults to 1.0 seconds.

Upstream starts a lane change at 20 mph (v_ego < 20 * MPH_TO_MS is false).
The extra gate in desire_helper is Mike's requested strict above 25 mph. It
is not an upstream threshold.

The blind-spot check is the upstream boolean: the blinker-side carState
leftBlindspot or rightBlindspot value. A false value is what that pull request
treats as clear. On this Tesla port that boolean is DAS_blindSpotRear* != 0,
so only NO_WARNING is false. A missing or stale frame can also be false. That
is the upstream limitation. It is not a measured rear gap, and this port does
not claim the maneuver is safe or vehicle-validated.

This project uses the design from Haibin Wen and SUNNYPILOT LLC. The sunnypilot
license at that commit requires permission for commercial or closed-source use.
"""

from openpilot.common.realtime import DT_MDL

# Upstream ONE_SECOND_DELAY. While blind-spot delay is on, the wait timer is
# parked at delay + this value, except for the 0.05 s nudgeless preset.
ONE_SECOND_DELAY = -1.0
NUDGELESS_PRESET_S = 0.05

# Documented adaptation. Upstream PR 653 does not use 25 mph.
USER_MIN_SPEED_MPH = 25.0


class BlinkerLaneChange:
  def __init__(self):
    self.wait_timer = 0.0
    self.delay_s = 0.0
    self.prev_brake_pressed = False
    self.prev_lane_change = False
    self.allowed = False

  def reset(self) -> None:
    self.wait_timer = 0.0
    self.prev_brake_pressed = False
    self.prev_lane_change = False
    self.allowed = False

  def update(self, *, nudgeless: bool, delay_s: float, bsm_delay: bool,
             blindspot_detected: bool, brake_pressed: bool) -> None:
    if brake_pressed and not self.prev_brake_pressed:
      self.prev_brake_pressed = True

    self.delay_s = max(float(delay_s), 0.0)
    self.wait_timer += DT_MDL
    if bsm_delay and blindspot_detected and self.delay_s > 0.0:
      if self.delay_s == NUDGELESS_PRESET_S:
        self.wait_timer = ONE_SECOND_DELAY
      else:
        self.wait_timer = self.delay_s + ONE_SECOND_DELAY

    if not nudgeless or self.prev_brake_pressed or self.prev_lane_change:
      self.allowed = False
      return
    self.allowed = self.wait_timer > self.delay_s

  def note_state(self, lane_change_off: bool, lane_change_starting: bool) -> None:
    if lane_change_starting:
      self.prev_lane_change = True
    if lane_change_off:
      self.reset()
