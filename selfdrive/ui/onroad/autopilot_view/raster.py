"""Software raster of the one-lane scene. No window and no extra package."""
from __future__ import annotations

import numpy as np

BG = np.array([0.86, 0.87, 0.88], dtype=np.float32)
_LIGHT = np.array([-0.3, 1.0, -0.4], dtype=np.float64)
_LIGHT /= np.linalg.norm(_LIGHT)

# Chase camera for the 536x240 frame. Lower and closer than the mockup
# eye (0, 7.5, -13.5) looking at (0, 0, 16) with a 42° vertical FOV.
# 44° (rather than 48°) keeps the car and lane large enough on this short screen.
CAMERA_EYE = (0.0, 5.2, -9.5)
CAMERA_TARGET = (0.0, 0.4, 20.0)
CAMERA_FOV_DEG = 44.0


def _view(width: int, height: int) -> np.ndarray:
  fov = np.radians(CAMERA_FOV_DEG)
  aspect = width / max(1, height)
  near, far = 0.5, 400.0
  t = 1.0 / np.tan(fov / 2.0)
  persp = np.array([
    [t / aspect, 0, 0, 0],
    [0, t, 0, 0],
    [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)],
    [0, 0, -1, 0],
  ], dtype=np.float64)
  eye = np.array(CAMERA_EYE, dtype=np.float64)
  center = np.array(CAMERA_TARGET, dtype=np.float64)
  forward = center - eye
  forward /= np.linalg.norm(forward)
  side = np.cross(forward, np.array([0.0, 1.0, 0.0]))
  side /= np.linalg.norm(side)
  up = np.cross(side, forward)
  look = np.eye(4)
  look[0, :3] = side
  look[1, :3] = up
  look[2, :3] = -forward
  look[:3, 3] = -look[:3, :3] @ eye
  return persp @ look


def _shade_cars(tris: np.ndarray, normals: np.ndarray, colors: np.ndarray) -> np.ndarray:
  diffuse = np.clip(normals @ _LIGHT, 0.0, None)
  hemi = 0.5 + 0.5 * normals[:, 1]
  lit = colors * (0.42 + 0.38 * diffuse[:, None] + 0.25 * hemi[:, None])
  center = tris.mean(axis=1)
  fog = np.clip((np.hypot(center[:, 0], center[:, 2]) - 40.0) / 80.0, 0.0, 1.0)
  return lit * (1.0 - fog[:, None] * 0.85) + BG * (fog[:, None] * 0.85)


def _project(tris: np.ndarray, mvp: np.ndarray, width: int, height: int):
  count = len(tris)
  homo = np.concatenate([tris, np.ones((count, 3, 1))], axis=2).reshape(-1, 4)
  clip = homo @ mvp.T
  w = clip[:, 3:4]
  ndc = clip[:, :3] / np.where(np.abs(w) < 1e-6, 1e-6, w)
  screen = np.empty((count, 3, 3), dtype=np.float64)
  ndc = ndc.reshape(count, 3, 3)
  w = w.reshape(count, 3)
  screen[:, :, 0] = (ndc[:, :, 0] * 0.5 + 0.5) * width
  screen[:, :, 1] = (1.0 - (ndc[:, :, 1] * 0.5 + 0.5)) * height
  screen[:, :, 2] = ndc[:, :, 2]
  return screen, w


def _paint(image: np.ndarray, depth: np.ndarray, screen, w, colors, alpha: float, ztest: bool) -> None:
  height, width = image.shape[:2]
  for tri, weights, color in zip(screen, w, colors, strict=False):
    if np.any(weights <= 0):
      continue
    x0 = max(int(np.floor(tri[:, 0].min())), 0)
    x1 = min(int(np.ceil(tri[:, 0].max())), width - 1)
    y0 = max(int(np.floor(tri[:, 1].min())), 0)
    y1 = min(int(np.ceil(tri[:, 1].max())), height - 1)
    if x1 < x0 or y1 < y0:
      continue
    xs = np.arange(x0, x1 + 1) + 0.5
    ys = np.arange(y0, y1 + 1) + 0.5
    px, py = np.meshgrid(xs, ys)
    area = ((tri[1, 0] - tri[0, 0]) * (tri[2, 1] - tri[0, 1]) -
            (tri[2, 0] - tri[0, 0]) * (tri[1, 1] - tri[0, 1]))
    if abs(area) < 1e-8:
      continue
    w0 = ((tri[1, 0] - px) * (tri[2, 1] - py) - (tri[2, 0] - px) * (tri[1, 1] - py)) / area
    w1 = ((tri[2, 0] - px) * (tri[0, 1] - py) - (tri[0, 0] - px) * (tri[2, 1] - py)) / area
    w2 = 1.0 - w0 - w1
    mask = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    if not np.any(mask):
      continue
    zee = w0 * tri[0, 2] + w1 * tri[1, 2] + w2 * tri[2, 2]
    if ztest:
      mask &= zee < depth[y0:y1 + 1, x0:x1 + 1]
      depth[y0:y1 + 1, x0:x1 + 1][mask] = zee[mask]
    patch = image[y0:y1 + 1, x0:x1 + 1]
    blended = color * alpha + patch * (1.0 - alpha)
    patch[mask] = blended[mask]


def render_scene(scene: dict, width: int, height: int) -> np.ndarray:
  image = np.empty((height, width, 3), dtype=np.float32)
  image[:] = BG
  depth = np.full((height, width), np.inf, dtype=np.float32)
  mvp = _view(width, height)
  for tris, colors, alpha in scene["lines"]:
    if len(tris) == 0:
      continue
    _paint(image, depth, *_project(tris, mvp, width, height), colors, alpha, False)
  path_tris, path_colors, path_alpha = scene["path"]
  if len(path_tris):
    _paint(image, depth, *_project(path_tris, mvp, width, height), path_colors, path_alpha, False)
  for tris, normals, colors in scene["cars"]:
    shaded = _shade_cars(tris, normals, colors)
    _paint(image, depth, *_project(tris, mvp, width, height), shaded, 1.0, True)
  return np.clip(image * 255.0, 0, 255).astype(np.uint8)
