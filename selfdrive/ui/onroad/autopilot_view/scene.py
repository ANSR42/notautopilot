"""One lane, from data the onroad UI already receives.

modelV2 lane lines are indexed left-left, left, right, right-right. Only the
middle pair bounds our lane. Openpilot +x is forward and +y is left. The
scene's +X is right and +Z is forward, matching the one-lane mock.
"""
from __future__ import annotations

import numpy as np

from openpilot.selfdrive.ui.onroad.autopilot_view.meshes import ego_mesh, lead_mesh
from openpilot.selfdrive.ui.onroad.notautopilot_engaged import PATH_BLUE_RGB

OWN_LANE = (1, 2)
LANE_PROB = 0.3
LEAD_DIFFERENT_M = 4.0
LEAD_DIFFERENT_Y = 1.5
PATH_HALF_M = 1.0
LINE_HALF_M = 0.07
PATH_BLUE = tuple(channel / 255.0 for channel in PATH_BLUE_RGB)

_EGO = ego_mesh()
_LEAD = lead_mesh()


def different_lead(primary, other) -> bool:
  return abs(other[0] - primary[0]) > LEAD_DIFFERENT_M or abs(other[1] - primary[1]) > LEAD_DIFFERENT_Y


def select_leads(leads: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
  """leadOne, plus leadTwo only when it is not the same car."""
  if not leads:
    return []
  chosen = [leads[0]]
  for other in leads[1:]:
    if different_lead(leads[0], other):
      chosen.append(other)
  return chosen


def _ribbon(xs, ys, half_width: float, y0: float) -> np.ndarray:
  xs = np.asarray(xs, dtype=np.float64)
  ys = np.asarray(ys, dtype=np.float64)
  if len(xs) < 2:
    return np.zeros((0, 3, 3), dtype=np.float32)
  pts = np.stack([-ys, np.full(len(xs), y0), xs], axis=1)
  forward = np.gradient(pts, axis=0)
  forward /= np.linalg.norm(forward, axis=1, keepdims=True) + 1e-9
  side = np.stack([forward[:, 2], np.zeros(len(xs)), -forward[:, 0]], axis=1)
  left = pts + side * half_width
  right = pts - side * half_width
  tris = np.empty((len(xs) - 1, 2, 3, 3), dtype=np.float32)
  tris[:, 0, 0] = left[:-1]
  tris[:, 0, 1] = right[:-1]
  tris[:, 0, 2] = left[1:]
  tris[:, 1, 0] = right[:-1]
  tris[:, 1, 1] = right[1:]
  tris[:, 1, 2] = left[1:]
  return tris.reshape(-1, 3, 3)


def _shade_flat(tris: np.ndarray, color) -> tuple[np.ndarray, np.ndarray]:
  if len(tris) == 0:
    return tris, np.zeros((0, 3), dtype=np.float32)
  return tris, np.tile(np.array(color, dtype=np.float32), (len(tris), 1))


def _place(mesh, x: float, z: float):
  tris, normals, colors = mesh
  out = tris.copy()
  out[:, :, 0] += x
  out[:, :, 2] += z
  return out, normals, colors


def build_scene(lane_xs, lane_ys, lane_probs, path_x, path_y, engaged: bool,
                leads: list[tuple[float, float, float]]) -> dict:
  """Return drawable parts. Road edges and the other lanes are not included."""
  lines = []
  for index in OWN_LANE:
    if index >= len(lane_probs) or float(lane_probs[index]) <= LANE_PROB:
      continue
    tris = _ribbon(lane_xs[index], lane_ys[index], LINE_HALF_M, 0.01)
    prob = float(lane_probs[index])
    lines.append((*_shade_flat(tris, (0.97, 0.97, 0.98)), min(1.0, prob + 0.2)))
  path = np.zeros((0, 3, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)
  if engaged and len(path_x) >= 2:
    path = _shade_flat(_ribbon(path_x[:28], path_y[:28], PATH_HALF_M, 0.015), PATH_BLUE)
  cars = [_place(_EGO, 0.0, 0.0)]
  for distance, lateral, _speed in select_leads(leads):
    cars.append(_place(_LEAD, -float(lateral), float(distance) + 2.4))
  return {"lines": lines, "path": (*path, 0.55 if engaged else 0.0), "cars": cars}
