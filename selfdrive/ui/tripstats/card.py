# Ported from TeslaPilot (MIT), Memberoffoxhound/TeslaPilot, branch Highland-Dev.
# https://github.com/Memberoffoxhound/TeslaPilot

"""Pure formatting for the drive summary card."""
from __future__ import annotations

from openpilot.selfdrive.ui.tripstats.recorder import CODES, MANUAL
from openpilot.selfdrive.ui.tripstats.store import engaged_pct

MIN_SHOW_M = 160.9
MIN_SHOW_S = 30.0
COL_GAP = 10
COMMA_GREEN = (0x17, 0x86, 0x45)


def eligible(drive: dict | None) -> bool:
  return bool(drive) and float(drive.get("m") or 0) >= MIN_SHOW_M and float(drive.get("dur") or 0) >= MIN_SHOW_S


def fmt_dist(meters: float, metric: bool) -> tuple[str, str]:
  d = meters / 1000.0 if metric else meters / 1609.344
  return (f"{d:.1f}" if d < 9.95 else f"{int(round(d))}"), ("km" if metric else "mi")


def card_columns(drive: dict, streak_days: int, metric: bool) -> list[tuple[str, str, str]]:
  m, e, best = float(drive.get("m") or 0), float(drive.get("e") or 0), float(drive.get("best_m") or 0)
  dv, du = fmt_dist(m, metric)
  bv, bu = fmt_dist(best, metric)
  return [
    (dv, du, "driven"),
    (str(engaged_pct(e, m)), "%", "engaged"),
    (bv, bu, "streak"),
    (str(int(streak_days)), "", "day streak"),
  ]


def column_slots(cols, avail: float, value_w, label_w, gap: float = COL_GAP) -> list[tuple[float, float, float]]:
  widths = [(value_w(v, u), label_w(lbl)) for v, u, lbl in cols]

  def fits(n: int) -> bool:
    slot = avail / n
    ws = [max(vw, lw) for vw, lw in widths[:n]]
    return (all((a + b) / 2 + gap <= slot for a, b in zip(ws, ws[1:], strict=False)) and
            ws[0] <= slot and ws[-1] <= slot)

  n = len(cols)
  while n > 3 and not fits(n):
    n -= 1
  slot = avail / max(1, n)
  return [(slot * (i + 0.5), vw, lw) for i, (vw, lw) in enumerate(widths[:n])]


def timeline_runs(codes: str) -> list[tuple[int, int, int]]:
  runs: list[tuple[int, int, int]] = []
  for i, ch in enumerate(codes):
    st = CODES.find(ch)
    st = MANUAL if st < 0 else st
    if runs and runs[-1][0] == st:
      runs[-1] = (st, runs[-1][1], runs[-1][2] + 1)
    else:
      runs.append((st, i, 1))
  return runs


def timeline_rects(x: float, y: float, w: float, h: float, runs: list[tuple[int, int, int]], n: int) -> list[tuple[float, float, float, float, int]]:
  """Colored runs across the full bar. Every bucket is visible, including the ends."""
  if n <= 0 or w <= 0 or h <= 0:
    return []
  rects = []
  for st, start, length in runs:
    x0 = x + w * start / n
    x1 = x + w * (start + length) / n
    if x1 > x0:
      rects.append((x0, y, x1 - x0, h, st))
  return rects


def card_layout(width: float, height: float, columns: list[tuple[str, str, str]], codes: str) -> dict:
  """Positions for a full-screen card. Small screens keep all four stats and the timeline on screen."""
  small = height <= 360
  pad = 12.0 if small else 64.0
  title_size = 26.0 if small else 56.0
  value_size = 28.0 if small else 64.0
  unit_size = 14.0 if small else 26.0
  label_size = 13.0 if small else 22.0
  title_y = 10.0 if small else 48.0
  value_y = 52.0 if small else 180.0
  label_y = 88.0 if small else 270.0
  bar_h = 22.0 if small else 28.0
  bar_y = 128.0 if small else 360.0
  bar_y = min(bar_y, height - bar_h - (12.0 if small else 48.0))
  avail = max(1.0, width - 2 * pad)
  slot = avail / max(1, len(columns))
  cols = []
  for i, (value, unit, label) in enumerate(columns):
    cols.append({
      "value": value, "unit": unit, "label": label,
      "center": pad + slot * (i + 0.5),
      "value_y": value_y, "label_y": label_y,
      "value_size": value_size, "unit_size": unit_size, "label_size": label_size,
    })
  bar = (pad, bar_y, avail, bar_h)
  runs = timeline_runs(codes)
  return {
    "background": (0.0, 0.0, width, height),
    "title": (pad, title_y, title_size),
    "columns": cols,
    "timeline": bar,
    "segments": timeline_rects(bar[0], bar[1], bar[2], bar[3], runs, len(codes)),
  }
