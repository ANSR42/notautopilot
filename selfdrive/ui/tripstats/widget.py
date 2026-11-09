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

PAD = 18
CHIP_H = 64


def _full_critical() -> bool:
  sm = ui_state.sm
  if not getattr(sm, "valid", {}).get("selfdriveState"):
    return False
  ss = sm["selfdriveState"]
  return (ss.alertSize == log.SelfdriveState.AlertSize.full and
          ss.alertStatus == log.SelfdriveState.AlertStatus.critical)


def _hit(rect: rl.Rectangle, event) -> bool:
  return rect.x <= event.pos.x <= rect.x + rect.width and rect.y <= event.pos.y <= rect.y + rect.height


def render(rect: rl.Rectangle) -> None:
  """Draw over the current page. Consumes a tap on the card or the replay chip."""
  if presenter.drive is None:
    return
  if _full_critical():
    return
  events = gui_app.mouse_events
  if presenter.visible:
    card = rl.Rectangle(rect.x + 40, rect.y + 80, rect.width - 80, min(420, rect.height - 160))
    if any(ev.left_released and _hit(card, ev) for ev in events):
      presenter.tap()
      gui_app.mouse_events[:] = [ev for ev in events if not (ev.left_released and _hit(card, ev))]
      return
    _draw_card(card)
    return
  chip = rl.Rectangle(rect.x + (rect.width - 280) / 2, rect.y + rect.height - CHIP_H - 36, 280, CHIP_H)
  if any(ev.left_released and _hit(chip, ev) for ev in events):
    presenter.reopen()
    gui_app.mouse_events[:] = [ev for ev in events if not (ev.left_released and _hit(chip, ev))]
    return
  rl.draw_rectangle_rounded(chip, 0.4, 8, rl.Color(23, 134, 69, 230))
  font = gui_app.font(FontWeight.BOLD)
  label = "Trip summary"
  width = measure_text_cached(font, label, 28).x
  rl.draw_text_ex(font, label, rl.Vector2(chip.x + (chip.width - width) / 2, chip.y + 16), 28, 0, rl.WHITE)


def _draw_card(rect: rl.Rectangle) -> None:
  drive = presenter.drive or {}
  stats = tripstats.view(drive if presenter.headline.startswith("last") else None)
  cols = tc.card_columns(drive, stats["streak_days"], bool(ui_state.is_metric))
  bold = gui_app.font(FontWeight.BOLD)
  roman = gui_app.font(FontWeight.ROMAN)
  rl.draw_rectangle_rounded(rect, 0.04, 8, rl.Color(7, 17, 27, 245))
  rl.draw_text_ex(bold, presenter.headline, rl.Vector2(rect.x + PAD, rect.y + 16), 42, 0, rl.WHITE)
  avail = rect.width - 2 * PAD
  slots = tc.column_slots(
    cols, avail,
    lambda v, u: measure_text_cached(bold, v, 40).x + (8 + measure_text_cached(bold, u, 22).x if u else 0),
    lambda lbl: measure_text_cached(roman, lbl, 20).x,
  )
  for (value, unit, label), (center, _vw, lw) in zip(cols, slots, strict=False):
    x = rect.x + PAD + center
    rl.draw_text_ex(bold, value, rl.Vector2(x - measure_text_cached(bold, value, 40).x / 2, rect.y + 80), 40, 0, rl.WHITE)
    if unit:
      rl.draw_text_ex(bold, unit, rl.Vector2(x + 8, rect.y + 96), 22, 0, rl.Color(255, 255, 255, 200))
    rl.draw_text_ex(roman, label, rl.Vector2(x - lw / 2, rect.y + 132), 20, 0, rl.Color(255, 255, 255, 200))
  runs = tc.timeline_runs(str(drive.get("tl") or ""))
  n = len(str(drive.get("tl") or ""))
  bar = rl.Rectangle(rect.x + PAD, rect.y + 180, avail, 18)
  rl.draw_rectangle_rounded(bar, 1.0, 8, rl.Color(255, 255, 255, 38))
  for x, y, w, h, status in tc.timeline_rects(bar.x, bar.y, bar.width, bar.height, runs, n):
    rgb = COLORS[status]
    rl.draw_rectangle(int(x), int(y), int(w), int(h), rl.Color(rgb[0], rgb[1], rgb[2], 255))
