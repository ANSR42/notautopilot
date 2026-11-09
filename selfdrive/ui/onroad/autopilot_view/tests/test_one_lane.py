import time

import numpy as np
from PIL import Image

from openpilot.selfdrive.ui.onroad.autopilot_view.meshes import ego_mesh, lead_mesh
from openpilot.selfdrive.ui.onroad.autopilot_view import raster
from openpilot.selfdrive.ui.onroad.autopilot_view.raster import render_scene
from openpilot.selfdrive.ui.onroad.autopilot_view.scene import PATH_BLUE, build_scene, select_leads
from openpilot.selfdrive.ui.onroad.notautopilot_engaged import PATH_BLUE_RGB


def _view_at(eye, center, fov_deg):
  """Same look-at matrix as the raster, with an explicit chase camera."""

  def _view(width, height):
    fov = np.radians(fov_deg)
    aspect = width / max(1, height)
    near, far = 0.5, 400.0
    scale = 1.0 / np.tan(fov / 2.0)
    persp = np.array([
      [scale / aspect, 0, 0, 0],
      [0, scale, 0, 0],
      [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)],
      [0, 0, -1, 0],
    ], dtype=np.float64)
    eye_a = np.array(eye, dtype=np.float64)
    center_a = np.array(center, dtype=np.float64)
    forward = center_a - eye_a
    forward /= np.linalg.norm(forward)
    side = np.cross(forward, np.array([0.0, 1.0, 0.0]))
    side /= np.linalg.norm(side)
    up = np.cross(side, forward)
    look = np.eye(4)
    look[0, :3] = side
    look[1, :3] = up
    look[2, :3] = -forward
    look[:3, 3] = -look[:3, :3] @ eye_a
    return persp @ look

  return _view


def _road(engaged=True, leads=None):
  xs = np.linspace(0, 80, 40)
  lanes_y = [np.full_like(xs, 3.6), np.full_like(xs, 1.8), np.full_like(xs, -1.8), np.full_like(xs, -3.6)]
  return build_scene([xs] * 4, lanes_y, [0.9, 0.95, 0.92, 0.8], xs, np.zeros_like(xs), engaged, leads or [])


def test_only_our_lane_and_a_distinct_second_lead():
  leads = select_leads([(12.0, 0.1, 8.0), (13.0, 0.2, 8.0), (30.0, -3.0, 9.0)])
  assert len(leads) == 2
  assert leads[1][0] == 30.0
  scene = _road(True, [(12.0, 0.0, 8.0), (13.0, 0.1, 8.0)])
  assert len(scene["lines"]) == 2
  assert len(scene["cars"]) == 2
  assert len(scene["path"][0]) > 0
  assert tuple(scene["path"][1][0]) == tuple(np.float32(PATH_BLUE))
  assert PATH_BLUE_RGB == (89, 150, 255)


def test_disengaged_has_no_path_and_the_mesh_stays_small():
  scene = _road(False, [])
  assert len(scene["path"][0]) == 0
  assert len(scene["lines"]) == 2
  assert len(ego_mesh()[0]) <= 200
  assert len(lead_mesh()[0]) <= 200
  low = _road(True)
  # A faint outside line is dropped.
  quiet = build_scene(
    [np.linspace(0, 40, 8)] * 4,
    [np.zeros(8), np.ones(8), -np.ones(8), np.full(8, 4.0)],
    [0.1, 0.9, 0.2, 0.9],
    np.linspace(0, 40, 8), np.zeros(8), True, [],
  )
  assert len(quiet["lines"]) == 1
  assert low["path"][2] == 0.55


def test_comma_four_frame_cost_and_screenshots():
  scene = _road(True, [(22.0, 0.0, 12.0)])
  render_scene(scene, 536, 240)
  started = time.perf_counter()
  frames = 6
  for _ in range(frames):
    image = render_scene(scene, 536, 240)
  elapsed_ms = (time.perf_counter() - started) / frames * 1000.0
  print(f"autopilot view 536x240 mean {elapsed_ms:.1f} ms")
  assert elapsed_ms < 80.0
  plain = render_scene(_road(False, []), 536, 240)
  out = __import__("pathlib").Path("/opt/cursor/artifacts")
  out.mkdir(parents=True, exist_ok=True)
  Image.fromarray(image).save(out / "autopilot_view_engaged.png")
  Image.fromarray(plain).save(out / "autopilot_view_disengaged.png")
  previous = _view_at((0.0, 7.5, -13.5), (0.0, 0.0, 16.0), 42.0)
  saved = raster._view
  raster._view = previous
  try:
    before = render_scene(scene, 536, 240)
  finally:
    raster._view = saved
  compare = Image.new("RGB", (536 * 2 + 4, 240), (12, 14, 16))
  compare.paste(Image.fromarray(before), (0, 0))
  compare.paste(Image.fromarray(image), (540, 0))
  compare.save(out / "autopilot_view_angle_compare.png")
  assert image.shape == (240, 536, 3)
  assert image[0, 0].tolist() == [219, 221, 224]
  blue = (image[:, :, 2].astype(int) > image[:, :, 0].astype(int) + 40) & (image[:, :, 2] > 160)
  plain_blue = (plain[:, :, 2].astype(int) > plain[:, :, 0].astype(int) + 40) & (plain[:, :, 2] > 160)
  assert int(blue.sum()) > int(plain_blue.sum()) + 40
