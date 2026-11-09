"""Custom wheel presentation. Blue path and control gates are not changed."""

from types import SimpleNamespace

from cereal import log
from PIL import Image

from openpilot.selfdrive.ui.lib.notautopilot_wordmark import SOURCE_CROP, WORDMARK_NATIVE, fitted_size
from openpilot.selfdrive.ui.onroad.notautopilot_engaged import (
  AVAILABLE,
  ENGAGED,
  HIDDEN,
  badge_presentation,
  badge_presentation_from_ui,
  engaged_path_rgba,
  show_notautopilot_engaged_icon,
)


State = log.SelfdriveState.OpenpilotState


def _mark(state, engageable, *, lat=False, long=False, longitudinal=True, state_valid=True,
          car_valid=True, aol=False):
  return badge_presentation(state, lat, long, longitudinal, engageable, state_valid, car_valid, aol)


def test_gray_only_when_disengaged_and_engageable():
  assert _mark(State.disabled, True) == AVAILABLE
  assert _mark(State.enabled, True, lat=True, long=True) == ENGAGED
  assert _mark(State.disabled, False) == HIDDEN
  assert _mark(State.disabled, None) == HIDDEN


def test_blocked_override_aol_and_stale_stay_hidden():
  assert _mark(State.preEnabled, True) == HIDDEN
  assert _mark(State.overriding, True, lat=True, long=False) == HIDDEN
  assert _mark(State.softDisabling, True, lat=True, long=True) == HIDDEN
  assert _mark(State.disabled, True, aol=True) == HIDDEN
  assert _mark(State.disabled, True, state_valid=False) == HIDDEN
  assert _mark(State.disabled, True, car_valid=False) == HIDDEN
  # Enabled without lateral control is not the blue badge and is not "available".
  assert _mark(State.enabled, True, lat=False, long=True) == HIDDEN


class _SubMaster:
  """The membership contract of cereal.messaging.SubMaster, without sockets."""

  def __init__(self, services, values, valid):
    self.services = list(services)
    self.data = dict(values)
    self.valid = dict(valid)
    self.sock = {name: object() for name in services}
    self.updated = {name: True for name in services}
    self.alive = {name: True for name in services}

  def __getitem__(self, key):
    return self.data[key]


def test_badge_uses_submaster_data_and_does_not_probe_integer_keys():
  sm = _SubMaster(
    ["selfdriveState", "carState", "carControl"],
    {
      "selfdriveState": SimpleNamespace(state=State.disabled, engageable=True),
      "carState": SimpleNamespace(),
      "carControl": SimpleNamespace(latActive=False, longActive=False),
    },
    {"selfdriveState": True, "carState": True, "carControl": True},
  )
  try:
    "selfdriveState" in sm
  except KeyError as exc:
    assert exc.args == (0,)
  else:
    raise AssertionError("SubMaster membership must not succeed through integer getitem")

  ui = SimpleNamespace(sm=sm, has_longitudinal_control=True, always_on_lateral_active=False)
  assert badge_presentation_from_ui(ui) == AVAILABLE

  sm.data["selfdriveState"] = SimpleNamespace(state=State.enabled, engageable=True)
  sm.data["carControl"] = SimpleNamespace(latActive=True, longActive=True)
  assert badge_presentation_from_ui(ui) == ENGAGED

  sm.data["selfdriveState"] = SimpleNamespace(state=State.disabled, engageable=True)
  sm.data["carControl"] = SimpleNamespace(latActive=False, longActive=False)
  sm.valid["carState"] = False
  assert badge_presentation_from_ui(ui) == HIDDEN


def test_blue_path_gate_ignores_engageable():
  assert show_notautopilot_engaged_icon(State.enabled, True, True, True)
  assert not show_notautopilot_engaged_icon(State.disabled, False, False, True)
  assert engaged_path_rgba((48, 255, 156, 90), False) == (48, 255, 156, 90)


def test_available_disc_is_gray_and_wheel_stays_light():
  icon = Image.open("selfdrive/assets/notautopilot/icon.png").convert("RGBA")
  gray = Image.open("selfdrive/assets/notautopilot/icon_available.png").convert("RGBA")
  assert icon.size == gray.size
  # Disc sample from the committed badge, outside the white wheel.
  assert gray.getpixel((512, 200))[0] == gray.getpixel((512, 200))[1]
  assert gray.getpixel((512, 200))[0] < 140
  assert min(gray.getpixel((512, 512))[:3]) > 220


def rebuild_wordmark():
  banner = Image.open("selfdrive/assets/notautopilot/source/banner-mike-nov6.jpg").convert("RGB")
  left, top, right, bottom = SOURCE_CROP
  cropped = banner.crop((left, top, right + 1, bottom + 1))
  pixels = cropped.load()
  out = Image.new("RGBA", cropped.size, (0, 0, 0, 0))
  dest = out.load()
  for y in range(cropped.height):
    for x in range(cropped.width):
      red, green, blue = pixels[x, y]
      alpha = max(0, min(255, int((max(red, green, blue) - 24) * 255 / (255 - 24))))
      if alpha:
        dest[x, y] = (red, green, blue, alpha)
  return out


def test_start_screen_uses_the_crop_and_spinner_is_unchanged():
  from pathlib import Path
  root = Path("selfdrive/ui")
  big = (root / "layouts/home.py").read_text(encoding="utf-8")
  small = (root / "mici/layouts/home.py").read_text(encoding="utf-8")
  assert "WORDMARK_ASSET" in big and "WORDMARK_ASSET" in small
  assert 'UnifiedLabel("StarPilot"' not in small
  assert "font_weight=FontWeight.BRAND" not in big
  spinner = Path("system/ui/spinner.py").read_text(encoding="utf-8")
  assert "wordmark" not in spinner


def test_wordmark_is_the_banner_title_crop():
  built = rebuild_wordmark()
  saved = Image.open("selfdrive/assets/notautopilot/wordmark.png")
  assert built.size == WORDMARK_NATIVE
  assert list(built.getdata()) == list(saved.getdata())
  assert SOURCE_CROP[1] < 370
  width, height = fitted_size(*WORDMARK_NATIVE, 520, 36)
  assert width <= 520 and height <= 36
