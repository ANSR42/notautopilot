"""Offline trip-card pictures. No display and no device."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from openpilot.selfdrive.ui.tripstats.card import card_layout
from openpilot.selfdrive.ui.tripstats.recorder import COLORS

BG = (7, 17, 27)


def _font(size: float, bold: bool = False) -> ImageFont.FreeTypeFont:
  name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
  return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", max(8, int(size)))


def paint_card(path: Path, width: int, height: int, headline: str, columns, codes: str) -> None:
  layout = card_layout(width, height, columns, codes)
  image = Image.new("RGB", (width, height), BG)
  draw = ImageDraw.Draw(image)
  tx, ty, tsize = layout["title"]
  draw.text((tx, ty), headline, fill=(255, 255, 255), font=_font(tsize, True))
  for col in layout["columns"]:
    value_font = _font(col["value_size"], True)
    unit_font = _font(col["unit_size"], True)
    label_font = _font(col["label_size"])
    value_w = draw.textlength(col["value"], font=value_font)
    unit_w = draw.textlength(col["unit"], font=unit_font) if col["unit"] else 0
    gap = 4 if col["unit"] else 0
    group = value_w + gap + unit_w
    vx = col["center"] - group / 2
    draw.text((vx, col["value_y"]), col["value"], fill=(255, 255, 255), font=value_font)
    if col["unit"]:
      draw.text((vx + value_w + gap, col["value_y"] + (col["value_size"] - col["unit_size"]) * 0.55),
                col["unit"], fill=(220, 220, 220), font=unit_font)
    label_w = draw.textlength(col["label"], font=label_font)
    draw.text((col["center"] - label_w / 2, col["label_y"]), col["label"], fill=(210, 210, 210), font=label_font)
  bx, by, bw, bh = layout["timeline"]
  draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=bh / 2, fill=(30, 36, 44))
  for x, y, w, h, status in layout["segments"]:
    draw.rectangle((x, y, x + max(1, w), y + h), fill=COLORS[status])
  path.parent.mkdir(parents=True, exist_ok=True)
  image.save(path)
