# Ported from TeslaPilot (MIT), Memberoffoxhound/TeslaPilot, branch Highland-Dev.
# https://github.com/Memberoffoxhound/TeslaPilot
# The card is display only. It does not change steering, longitudinal control, or alerts.

"""On-screen trip summary. Tap dismisses it. A small replay chip brings it back before the next drive."""
from __future__ import annotations

import pyray as rl
from cereal import log

from openpilot.selfdrive.ui import tripstats
from openpilot.selfdrive.ui.tripstats import card as tc
from openpilot.selfdrive.ui.tripstats.presenter import presenter
from openpilot.selfdrive.ui.tripstats.recorder import COLORS
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached

BG = (7, 17, 27)


def _full_critical() -> bool:
  sm = ui_state.sm
  if not getattr(sm, "valid", {}).get("selfdriveState"):
    return False
  ss = sm["selfdriveState"]
  return (ss.alertSize == log.SelfdriveState.AlertSize.full and
          ss.alertStatus == log.SelfdriveState.AlertStatus.critical)


def _hit(rect: rl.Rectangle, event) -> bool:
  return rect.x <= event.pos.x <= rect.x + rect.width and rect.y <= event.pos.y <= rect.y + rect.height


def screen_rect() -> rl.Rectangle:
  """The physical framebuffer, not a scrolled page inside it."""
  return rl.Rectangle(0, 0, float(gui_app.width), float(gui_app.height))


def render(_rect: rl.Rectangle) -> None:
  """Full-screen card, or a small chip. The card covers every home widget."""
  if presenter.drive is None:
    return
  if _full_critical():
    return
  screen = screen_rect()
  events = gui_app.mouse_events
  if presenter.visible:
    if any(ev.left_released and _hit(screen, ev) for ev in events):
      presenter.tap()
      gui_app.mouse_events[:] = []
    _draw_card(screen)
    return
  chip_w = 168.0 if screen.height <= 360 else 280.0
  chip_h = 36.0 if screen.height <= 360 else 56.0
  chip = rl.Rectangle(screen.x + (screen.width - chip_w) / 2, screen.y + screen.height - chip_h - 8, chip_w, chip_h)
  if any(ev.left_released and _hit(chip, ev) for ev in events):
    presenter.reopen()
    gui_app.mouse_events[:] = [ev for ev in events if not (ev.left_released and _hit(chip, ev))]
    return
  rl.draw_rectangle_rounded(chip, 0.45, 8, rl.Color(23, 134, 69, 230))
  font = gui_app.font(FontWeight.BOLD)
  label = "Trip summary"
  size = 18 if screen.height <= 360 else 28
  width = measure_text_cached(font, label, size).x
  rl.draw_text_ex(font, label, rl.Vector2(chip.x + (chip.width - width) / 2, chip.y + (chip.height - size) / 2), size, 0, rl.WHITE)


def _draw_card(rect: rl.Rectangle) -> None:
  drive = presenter.drive or {}
  stats = tripstats.view(drive if presenter.headline.startswith("last") else None)
  cols = tc.card_columns(drive, stats["streak_days"], bool(ui_state.is_metric))
  layout = tc.card_layout(rect.width, rect.height, cols, str(drive.get("tl") or ""))
  bold = gui_app.font(FontWeight.BOLD)
  roman = gui_app.font(FontWeight.ROMAN)
  rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
  rl.draw_rectangle(int(rect.x), int(rect.y), int(rect.width), int(rect.height), rl.Color(*BG, 255))
  tx, ty, tsize = layout["title"]
  rl.draw_text_ex(bold, presenter.headline, rl.Vector2(rect.x + tx, rect.y + ty), tsize, 0, rl.WHITE)
  for col in layout["columns"]:
    value, unit, label = col["value"], col["unit"], col["label"]
    vw = measure_text_cached(bold, value, col["value_size"]).x
    uw = measure_text_cached(bold, unit, col["unit_size"]).x if unit else 0
    gap = 4 if unit else 0
    group = vw + gap + uw
    vx = rect.x + col["center"] - group / 2
    rl.draw_text_ex(bold, value, rl.Vector2(vx, rect.y + col["value_y"]), col["value_size"], 0, rl.WHITE)
    if unit:
      rl.draw_text_ex(
        bold, unit,
        rl.Vector2(vx + vw + gap, rect.y + col["value_y"] + (col["value_size"] - col["unit_size"]) * 0.72),
        col["unit_size"], 0, rl.Color(255, 255, 255, 210),
      )
    lw = measure_text_cached(roman, label, col["label_size"]).x
    rl.draw_text_ex(roman, label, rl.Vector2(rect.x + col["center"] - lw / 2, rect.y + col["label_y"]), col["label_size"], 0, rl.Color(255, 255, 255, 210))
  bx, by, bw, bh = layout["timeline"]
  rl.draw_rectangle_rounded(rl.Rectangle(rect.x + bx, rect.y + by, bw, bh), 1.0, 8, rl.Color(255, 255, 255, 36))
  for x, y, w, h, status in layout["segments"]:
    rgb = COLORS[status]
    rl.draw_rectangle(int(rect.x + x), int(rect.y + y), max(1, int(w)), int(h), rl.Color(*rgb, 255))
  rl.end_scissor_mode()
