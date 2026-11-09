"""Swappable low-poly cars for the one-lane view.

Replace `ego_mesh` in this file to drop in a later Model Y mesh.
Each mesh is (triangles Nx3x3, normals Nx3, colors Nx3) in meters.
Ego origin is the rear-bumper center, nose toward +Z, up is +Y.
"""
from __future__ import annotations

import numpy as np

_FACE = (
  (0, 1, 2), (0, 2, 3),  # front
  (5, 4, 7), (5, 7, 6),  # back
  (4, 0, 3), (4, 3, 7),  # left
  (1, 5, 6), (1, 6, 2),  # right
  (3, 2, 6), (3, 6, 7),  # top
  (4, 5, 1), (4, 1, 0),  # bottom
)


def _box(center, size, color) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
  cx, cy, cz = center
  hx, hy, hz = (size[0] / 2, size[1] / 2, size[2] / 2)
  corners = np.array([
    [cx - hx, cy - hy, cz + hz], [cx + hx, cy - hy, cz + hz],
    [cx + hx, cy + hy, cz + hz], [cx - hx, cy + hy, cz + hz],
    [cx - hx, cy - hy, cz - hz], [cx + hx, cy - hy, cz - hz],
    [cx + hx, cy + hy, cz - hz], [cx - hx, cy + hy, cz - hz],
  ], dtype=np.float32)
  tris = np.array([corners[list(face)] for face in _FACE], dtype=np.float32)
  normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
  normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-9
  colors = np.tile(np.array(color, dtype=np.float32), (len(tris), 1))
  return tris, normals, colors


def _join(parts):
  return tuple(np.concatenate(list(axis), axis=0) for axis in zip(*parts, strict=True))


def ego_mesh():
  """Dark Model Y placeholder, a few dozen boxes. Swap this function for a real mesh."""
  body = (0.07, 0.07, 0.08)
  glass = (0.03, 0.03, 0.04)
  lamp = (0.50, 0.05, 0.05)
  return _join([
    _box((0.0, 0.55, 2.35), (1.90, 0.70, 4.70), body),
    _box((0.0, 1.05, 2.55), (1.70, 0.48, 2.15), glass),
    _box((-0.70, 0.32, 0.35), (0.28, 0.48, 0.70), (0.02, 0.02, 0.02)),
    _box((0.70, 0.32, 0.35), (0.28, 0.48, 0.70), (0.02, 0.02, 0.02)),
    _box((-0.70, 0.32, 3.85), (0.28, 0.48, 0.70), (0.02, 0.02, 0.02)),
    _box((0.70, 0.32, 3.85), (0.28, 0.48, 0.70), (0.02, 0.02, 0.02)),
    _box((-0.72, 0.72, 0.12), (0.22, 0.10, 0.16), lamp),
    _box((0.72, 0.72, 0.12), (0.22, 0.10, 0.16), lamp),
  ])


def lead_mesh():
  body = (0.80, 0.80, 0.81)
  glass = (0.42, 0.43, 0.45)
  return _join([
    _box((0.0, 0.55, 0.0), (1.80, 0.68, 4.40), body),
    _box((0.0, 1.02, -0.15), (1.60, 0.46, 2.00), glass),
    _box((-0.68, 0.30, -1.45), (0.26, 0.46, 0.66), (0.55, 0.55, 0.56)),
    _box((0.68, 0.30, -1.45), (0.26, 0.46, 0.66), (0.55, 0.55, 0.56)),
    _box((-0.68, 0.30, 1.45), (0.26, 0.46, 0.66), (0.55, 0.55, 0.56)),
    _box((0.68, 0.30, 1.45), (0.26, 0.46, 0.66), (0.55, 0.55, 0.56)),
  ])
