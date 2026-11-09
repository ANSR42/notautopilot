import ctypes
from types import SimpleNamespace

import numpy as np
import pyray as rl

from openpilot.selfdrive.ui.onroad.autopilot_view import view as autopilot_view


class _RejectsCtypes:
  """pyray's cffi binding raises TypeError on a ctypes pointer."""

  def __init__(self) -> None:
    self.pointers = []

  def __call__(self, _tex, pointer):
    if isinstance(pointer, ctypes.c_void_p) or type(pointer).__module__ == "ctypes":
      raise TypeError("pyray expects a cffi cdata pointer, not ctypes.c_void_p")
    if not isinstance(pointer, rl.ffi.CData):
      raise TypeError(f"pyray expects a cffi cdata pointer, got {type(pointer)}")
    self.pointers.append(pointer)


def test_texture_update_passes_a_cffi_pointer(monkeypatch):
  upload = _RejectsCtypes()
  monkeypatch.setattr(rl, "update_texture", upload)
  monkeypatch.setattr(rl, "unload_texture", lambda *_a, **_k: None)
  monkeypatch.setattr(rl, "gen_image_color", lambda *_a, **_k: object())
  monkeypatch.setattr(rl, "load_texture_from_image", lambda *_a, **_k: SimpleNamespace(width=4, height=3))
  monkeypatch.setattr(rl, "unload_image", lambda *_a, **_k: None)
  monkeypatch.setattr(rl, "set_texture_filter", lambda *_a, **_k: None)

  image = np.zeros((3, 4, 3), dtype=np.uint8)
  image[0, 0] = (89, 150, 255)
  texture = autopilot_view._Texture()
  uploaded = texture.update(image)

  assert uploaded.width == 4 and uploaded.height == 3
  assert len(upload.pointers) == 1
  assert isinstance(upload.pointers[0], rl.ffi.CData)
  assert texture._pixels.flags["C_CONTIGUOUS"]
  assert texture._pixels.dtype == np.uint8
  assert texture._pixels.shape == (3, 4, 4)


def test_present_falls_back_to_the_standard_camera_and_logs_once(monkeypatch):
  logged = []
  monkeypatch.setattr(autopilot_view.cloudlog, "exception", lambda *_a, **_k: logged.append("logged"))
  autopilot_view._logged_failure = False

  def explode(_rect, _sm):
    raise TypeError("pyray expects a cffi cdata pointer, not ctypes.c_void_p")

  monkeypatch.setattr(autopilot_view, "render", explode)
  cameras = []
  rect = SimpleNamespace()
  sm = SimpleNamespace()
  autopilot_view.present(rect, sm, lambda: cameras.append("standard"))
  autopilot_view.present(rect, sm, lambda: cameras.append("standard"))

  assert cameras == ["standard", "standard"]
  assert logged == ["logged"]
