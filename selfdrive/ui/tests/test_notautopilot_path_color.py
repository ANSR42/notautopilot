"""Path ribbon color follows the blue-wheel engagement gate.

The driving-path ribbon is ModelRenderer._draw_path. This tree has no separate
painted "path desire" element. modelV2 desire and desiredCurvature are not
recolored or rewritten here.

test_lane_centering.py is a controller regression check, not this color change.
"""

from types import SimpleNamespace

from cereal import log

from openpilot.selfdrive.ui.onroad.notautopilot_engaged import (
  BADGE_BLUE_RGB,
  PATH_BLUE_RGB,
  engaged_icon_from_ui,
  engaged_path_rgba,
  show_notautopilot_engaged_icon,
)


State = log.SelfdriveState.OpenpilotState


def _contrast(a, b) -> float:
  def channel(value):
    value = value / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

  def luminance(rgb):
    red, green, blue = (channel(c) for c in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue

  lighter = max(luminance(a), luminance(b))
  darker = min(luminance(a), luminance(b))
  return (lighter + 0.05) / (darker + 0.05)


def test_engaged_path_keeps_alpha_and_uses_lighter_badge_hue():
  original = (48, 255, 156, 102)
  assert engaged_path_rgba(original, False) == original
  painted = engaged_path_rgba(original, True)
  assert painted[:3] == PATH_BLUE_RGB
  assert painted[3] == 102
  assert engaged_path_rgba((13, 248, 122, 0), True)[3] == 0
  assert _contrast(PATH_BLUE_RGB, (40, 40, 40)) >= 3.0
  assert _contrast(BADGE_BLUE_RGB, (50, 50, 50)) < 3.0


def test_path_blue_follows_wheel_gate_and_does_not_latch():
  frames = [
    (State.disabled, False, False, False),
    (State.enabled, True, True, True),
    (State.enabled, True, True, True),
    (State.overriding, True, False, True),
    (State.softDisabling, True, True, True),
    (State.preEnabled, True, True, True),
    (State.disabled, True, False, False),
    (State.enabled, False, True, True),
    (State.enabled, True, False, True),
  ]
  expected = [False, True, True, False, False, False, False, False, False]
  assert [show_notautopilot_engaged_icon(*frame) for frame in frames] == expected
  green = (48, 255, 156, 255)
  colors = [engaged_path_rgba(green, show_notautopilot_engaged_icon(*frame)) for frame in frames]
  assert colors[0] == green
  assert colors[1][:3] == PATH_BLUE_RGB
  assert colors[3] == green
  assert colors[4] == green


class _SM(dict):
  def __init__(self, valid, **items):
    super().__init__(items)
    self.valid = valid


def test_stale_control_does_not_paint_the_path_blue():
  ui = SimpleNamespace(
    has_longitudinal_control=True,
    sm=_SM(
      {"carControl": False, "selfdriveState": True},
      selfdriveState=SimpleNamespace(state=State.enabled),
      carControl=SimpleNamespace(latActive=True, longActive=True),
    ),
  )
  assert not engaged_icon_from_ui(ui)
  assert engaged_path_rgba((48, 255, 156, 90), engaged_icon_from_ui(ui)) == (48, 255, 156, 90)
