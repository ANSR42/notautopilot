import hashlib
from pathlib import Path

from cereal import log

from types import SimpleNamespace

from openpilot.selfdrive.ui.onroad.notautopilot_engaged import (
  ENGAGED_ICON_CROP,
  engaged_icon_from_ui,
  engaged_icon_source,
  show_notautopilot_engaged_icon,
)


State = log.SelfdriveState.OpenpilotState
ROOT = Path(__file__).resolve().parents[3]
BANNER = ROOT / "selfdrive" / "assets" / "notautopilot" / "banner.jpg"
ICON = ROOT / "selfdrive" / "assets" / "notautopilot" / "icon.png"
BANNER_SHA256 = "59e9355489d2f0cbfd6da2560b3e61ca5f1ae3a29a9133a436d0cac756682264"
ICON_SHA256 = "635a6eb8c79b61a8f319811e2a51250e303c1ad9e8fe1e00283712831bd370a3"


def test_banner_and_icon_are_the_supplied_bytes():
  assert hashlib.sha256(BANNER.read_bytes()).hexdigest() == BANNER_SHA256
  assert hashlib.sha256(ICON.read_bytes()).hexdigest() == ICON_SHA256
  readme = (ROOT / "README.md").read_text(encoding="utf-8")
  assert "selfdrive/assets/notautopilot/banner.jpg" in readme
  assert "Unofficial" in readme
  assert "notautopilot" in readme


def test_badge_requires_enabled_state_and_lateral_actuation():
  assert show_notautopilot_engaged_icon(State.enabled, True, True, True)
  assert show_notautopilot_engaged_icon(State.enabled, True, False, False)
  assert not show_notautopilot_engaged_icon(State.disabled, True, True, True)
  assert not show_notautopilot_engaged_icon(State.preEnabled, True, True, True)
  assert not show_notautopilot_engaged_icon(State.overriding, True, False, True)
  assert not show_notautopilot_engaged_icon(State.softDisabling, True, True, True)
  assert not show_notautopilot_engaged_icon(State.enabled, False, True, True)
  assert not show_notautopilot_engaged_icon(State.enabled, True, False, True)


def test_repeated_frames_follow_the_current_state_without_latching():
  frames = [
    (State.disabled, False, False, False),
    (State.enabled, True, True, True),
    (State.enabled, True, True, True),
    (State.overriding, True, False, True),
    (State.enabled, True, True, True),
    (State.softDisabling, True, True, True),
    (State.disabled, True, False, False),
  ]
  expected = [False, True, True, False, True, False, False]
  assert [show_notautopilot_engaged_icon(*frame) for frame in frames] == expected


class _SM(dict):
  def __init__(self, valid, **items):
    super().__init__(items)
    self.valid = valid


def _ui(state, lat_active, long_active, openpilot_longitudinal, valid=True):
  return SimpleNamespace(
    has_longitudinal_control=openpilot_longitudinal,
    sm=_SM(
      {"carControl": valid, "selfdriveState": True},
      selfdriveState=SimpleNamespace(state=state, enabled=state == State.enabled, engageable=True),
      carControl=SimpleNamespace(latActive=lat_active, longActive=long_active),
    ),
  )


def test_ui_reader_hides_badge_when_only_available_or_control_is_missing():
  available = _ui(State.disabled, False, False, False)
  assert not engaged_icon_from_ui(available)
  assert not engaged_icon_from_ui(_ui(State.enabled, True, True, True, valid=False))
  assert engaged_icon_from_ui(_ui(State.enabled, True, True, True))
  assert engaged_icon_from_ui(_ui(State.enabled, True, True, True))
  assert not engaged_icon_from_ui(_ui(State.overriding, True, False, True))


def test_icon_crop_stays_inside_the_committed_image():
  left, top, side = ENGAGED_ICON_CROP
  assert left >= 0 and top >= 0 and side > 0
  assert left + side <= 1024
  assert top + side <= 1024
  source_x, source_y, source_w, source_h = engaged_icon_source(512, 512)
  assert source_x == left / 2
  assert source_y == top / 2
  assert source_w == side / 2
  assert source_h == side / 2
