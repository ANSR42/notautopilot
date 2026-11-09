"""Blit the one-lane raster into the onroad view. Off unless CameraView is 5."""
from __future__ import annotations

import numpy as np
import pyray as rl

from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.onroad.autopilot_view.raster import render_scene
from openpilot.selfdrive.ui.onroad.autopilot_view.scene import build_scene

# Comma four's framebuffer is 536x240. Larger screens upscale this raster.
MAX_WIDTH = 536

CAMERA_VIEW_AUTOPILOT = 5


class _Texture:
  def __init__(self) -> None:
    self.tex = None
    self.size = (0, 0)
    self._pixels = None

  def update(self, image: np.ndarray):
    height, width = image.shape[:2]
    # Keep the buffer alive for the upload. pyray is cffi and rejects ctypes.c_void_p.
    self._pixels = np.ascontiguousarray(np.dstack([image, np.full((height, width), 255, np.uint8)]))
    if self.tex is None or self.size != (width, height):
      if self.tex is not None:
        rl.unload_texture(self.tex)
      blank = rl.gen_image_color(width, height, rl.BLACK)
      self.tex = rl.load_texture_from_image(blank)
      rl.unload_image(blank)
      rl.set_texture_filter(self.tex, rl.TEXTURE_FILTER_BILINEAR)
      self.size = (width, height)
    pointer = rl.ffi.cast("void *", rl.ffi.from_buffer(self._pixels))
    rl.update_texture(self.tex, pointer)
    return self.tex


_CACHE = _Texture()
_logged_failure = False


def _log_failure() -> None:
  global _logged_failure
  if not _logged_failure:
    _logged_failure = True
    cloudlog.exception("autopilot view")


def frame_from_messages(model, radar, engaged: bool) -> dict:
  lane_x, lane_y, probs = [], [], []
  lines = list(getattr(model, "laneLines", []) or [])
  raw_probs = list(getattr(model, "laneLineProbs", []) or [])
  for index, line in enumerate(lines):
    lane_x.append(line.x)
    lane_y.append(line.y)
    probs.append(raw_probs[index] if index < len(raw_probs) else 0.0)
  position = getattr(model, "position", None)
  path_x = list(getattr(position, "x", []) or [])
  path_y = list(getattr(position, "y", []) or [])
  leads = []
  if radar is not None:
    for lead in (getattr(radar, "leadOne", None), getattr(radar, "leadTwo", None)):
      if lead is not None and bool(getattr(lead, "status", False)):
        leads.append((float(lead.dRel), float(lead.yRel), float(getattr(lead, "vLead", 0.0))))
  return build_scene(lane_x, lane_y, probs, path_x, path_y, engaged, leads)


def render(rect: rl.Rectangle, sm) -> None:
  width = max(1, int(rect.width))
  height = max(1, int(rect.height))
  raster_w = min(width, MAX_WIDTH)
  raster_h = max(1, int(round(height * raster_w / width)))
  model = sm["modelV2"] if sm.valid.get("modelV2", False) else None
  radar = sm["radarState"] if sm.valid.get("radarState", False) else None
  if model is None:
    rl.draw_rectangle_rec(rect, rl.Color(219, 222, 224, 255))
    return
  from openpilot.selfdrive.ui.onroad.notautopilot_engaged import engaged_icon_from_ui
  from openpilot.selfdrive.ui.ui_state import ui_state
  scene = frame_from_messages(model, radar, engaged_icon_from_ui(ui_state))
  image = render_scene(scene, raster_w, raster_h)
  texture = _CACHE.update(image)
  rl.draw_texture_pro(
    texture,
    rl.Rectangle(0, 0, texture.width, texture.height),
    rect,
    rl.Vector2(0, 0),
    0.0,
    rl.WHITE,
  )


def present(rect: rl.Rectangle, sm, draw_camera) -> None:
  """Draw the one-lane view. Any failure logs once and draws the standard camera for this frame."""
  try:
    render(rect, sm)
  except Exception:
    _log_failure()
    draw_camera()
