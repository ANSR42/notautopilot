import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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
BANNER_SHA256 = "02679f2d9993543925f415bdd18f445ac8a6b82b1575d6027d2d80c7e4fe5dde"
TAGLINE = "what Tesla's autopilot should've been"
TAGLINE_FONT = "/usr/share/fonts/truetype/macos/Inter-Regular.ttf"
TAGLINE_SIZE = 40
TAGLINE_TRACKING = 0.6
TAGLINE_COLOR = (236, 236, 238)
TAGLINE_BOTTOM_MARGIN = 68
ICON_SHA256 = "635a6eb8c79b61a8f319811e2a51250e303c1ad9e8fe1e00283712831bd370a3"


def test_banner_and_icon_are_the_supplied_bytes():
  assert hashlib.sha256(BANNER.read_bytes()).hexdigest() == BANNER_SHA256
  source = ROOT / "selfdrive" / "assets" / "notautopilot" / "source" / "banner-mike-nov6.jpg"
  assert hashlib.sha256(source.read_bytes()).hexdigest() == "1d6c5fd88cb8afc0624c5c86ed59a4a2443e4745ed3c81ba1d2070f966e06210"
  assert hashlib.sha256(ICON.read_bytes()).hexdigest() == ICON_SHA256
  readme = (ROOT / "README.md").read_text(encoding="utf-8")
  assert "selfdrive/assets/notautopilot/banner.jpg" in readme
  assert "https://x.com/ANSR42" in readme
  assert "Unofficial" in readme
  assert "notautopilot" in readme
  assert TAGLINE in readme


def _draw_tagline(image: Image.Image) -> None:
  draw = ImageDraw.Draw(image)
  font = ImageFont.truetype(TAGLINE_FONT, TAGLINE_SIZE)
  advances = [draw.textbbox((0, 0), character, font=font)[2] for character in TAGLINE]
  total = sum(advances) + TAGLINE_TRACKING * (len(TAGLINE) - 1)
  x = (image.width - total) / 2
  y = image.height - TAGLINE_BOTTOM_MARGIN - draw.textbbox((0, 0), TAGLINE, font=font)[3]
  cursor = x
  for character, advance in zip(TAGLINE, advances, strict=True):
    draw.text((cursor, y), character, font=font, fill=TAGLINE_COLOR)
    cursor += advance + TAGLINE_TRACKING


def test_banner_tagline_matches_the_rendered_line():
  banner = Image.open(BANNER).convert("RGB")
  reference = Image.new("RGB", banner.size, (0, 0, 0))
  _draw_tagline(reference)
  xs = []
  ys = []
  ink = 0
  matched = 0
  for y in range(banner.height):
    for x in range(banner.width):
      if min(reference.getpixel((x, y))) < 160:
        continue
      ink += 1
      xs.append(x)
      ys.append(y)
      if min(banner.getpixel((x, y))) >= 140:
        matched += 1
  assert ink > 4000
  assert matched == ink
  assert abs((min(xs) + max(xs)) / 2 - banner.width / 2) < 8
  assert banner.height - 1 - max(ys) == TAGLINE_BOTTOM_MARGIN
  assert min(ys) > 580
  # Original NOTAUTOPILOT lettering stays in its band. The tagline does not enter it.
  title_ink = 0
  for y in range(297, 354):
    for x in range(549, 1210):
      if min(banner.getpixel((x, y))) > 180:
        title_ink += 1
  assert title_ink > 10000
  attribution = [banner.getpixel((x, 502)) for x in range(552, 740)]
  assert sum(min(pixel) > 140 for pixel in attribution) > 40


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
