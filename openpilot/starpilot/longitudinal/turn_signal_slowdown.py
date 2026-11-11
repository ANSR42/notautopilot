"""Blinker-gated curvature speed cap from the StarPilot 6.7.9 Taco Bell hack.

The cap is a cruise ceiling: callers may only min() it into the current cruise
speed. Chill and Experimental both consume that cruise speed, and the existing
cruise jerk and deceleration limits stay in charge of how quickly speed falls.
"""

import math
import os
from pathlib import Path
import tempfile

import numpy as np

from openpilot.common.params import UnknownKeyName
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import T_IDXS as T_IDXS_MPC
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.starpilot.saved_document import commit_exact
from openpilot.starpilot.saved_source import read_saved


KEY = "TacoTune"
LABEL = "Turn Signal Slowdown (Taco Bell)"
REASON = ("Lowers cruise speed for a tight predicted curve while exactly one turn signal is on. " +
          "Chill and Experimental both follow that lower limit, and braking stays within the planner comfort limits.")
_REFRESH_NS = 1_000_000_000


def curvature_speed_cap(v_ego, orientation_rate_z, model_velocity_x) -> float | None:
  """Minimum non-negative speed from the 6.7.9 formula, or None when the model frame is unusable."""
  try:
    rates = np.asarray(list(orientation_rate_z), dtype=float)
    speeds = np.asarray(list(model_velocity_x), dtype=float)
  except (TypeError, ValueError):
    return None
  if rates.shape != (ModelConstants.IDX_N,) or speeds.shape != (ModelConstants.IDX_N,):
    return None
  try:
    v_ego = float(v_ego)
  except (TypeError, ValueError):
    return None
  if not math.isfinite(v_ego):
    return None
  if not np.isfinite(rates).all() or not np.isfinite(speeds).all():
    return None
  predicted = np.interp(T_IDXS_MPC, ModelConstants.T_IDXS, speeds)
  lateral = float(np.interp(float(v_ego), [5.0, 10.0, 20.0], [1.5, 2.0, 3.0]))
  curvature = np.interp(T_IDXS_MPC, ModelConstants.T_IDXS, rates) / np.clip(predicted, 0.3, 100.0)
  allowed = np.sqrt(lateral / (np.abs(curvature) + 1e-3)) - 2.0
  if not np.isfinite(allowed).all():
    return None
  return float(max(0.0, np.min(allowed)))


def turn_signal_ceiling(sm, CP, cruise_mps: float, *, enabled: bool) -> float | None:
  """Speed the cruise ceiling may fall to, or None when the hack must leave the plan alone."""
  try:
    cruise_mps = float(cruise_mps)
  except (TypeError, ValueError):
    return None
  if enabled is not True or not math.isfinite(cruise_mps) or cruise_mps <= 0:
    return None
  try:
    car, control = sm["carState"], sm["carControl"]
    if (not CP.openpilotLongitudinalControl or CP.passive or CP.dashcamOnly or not control.longActive or
        not sm["selfdriveState"].enabled or sm["controlsState"].longControlState == LongCtrlState.off or
        car.gasPressed or str(car.gearShifter) != "drive" or bool(car.leftBlinker) == bool(car.rightBlinker)):
      return None
    cap = curvature_speed_cap(car.vEgo, sm["modelV2"].orientationRate.z, sm["modelV2"].velocity.x)
  except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
    return None
  if cap is None or cap >= cruise_mps:
    return None
  return cap


def registered(params) -> bool:
  """The key is in params_keys.h. A checkout still running the previous prebuilt
  libparams_c.so does not know it until that library is rebuilt."""
  try:
    params.check_key(KEY)
  except UnknownKeyName:
    return False
  return True


def _storage_root(root: Path | None) -> Path:
  if root is not None:
    return Path(root)
  from openpilot.starpilot.storage import starpilot_storage_root
  return starpilot_storage_root()


def _read_file(path: Path) -> tuple[bytes | None, bool]:
  try:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
  except FileNotFoundError:
    return None, True
  except OSError:
    return b"", False
  try:
    raw = os.read(fd, 16)
  except OSError:
    return b"", False
  finally:
    os.close(fd)
  if raw not in (b"0", b"1"):
    return raw, False
  return raw, True


def _fallback_off(root: Path | None) -> bool:
  try:
    raw, readable = _read_file(_storage_root(root) / KEY)
  except (OSError, ValueError):
    return False
  return readable and raw == b"0"


def read_enabled(params, *, root: Path | None = None) -> tuple[bool, bytes | None, bool]:
  """(enabled, raw, valid). A missing saved choice is on."""
  if registered(params):
    try:
      raw, readable = read_saved(params, KEY, 16)
    except (OSError, TypeError, ValueError):
      return False, b"", False
    if not readable or raw not in (None, b"0", b"1"):
      return False, raw, False
    if raw is None and _fallback_off(root):
      return False, None, True
    return raw in (None, b"1"), raw, True
  raw, readable = _read_file(_storage_root(root) / KEY)
  if not readable or raw not in (None, b"0", b"1"):
    return False, raw, False
  return raw in (None, b"1"), raw, True


def _write_file(path: Path, raw: bytes, expected: bytes | None) -> bool:
  current, readable = _read_file(path)
  if not readable or current != expected:
    return False
  temporary = None
  try:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", dir=path.parent, delete=False) as stage:
      temporary = stage.name
      stage.write(raw)
      stage.flush()
      os.fsync(stage.fileno())
    os.replace(temporary, path)
    temporary = None
  except OSError:
    return False
  finally:
    if temporary is not None:
      try:
        os.unlink(temporary)
      except OSError:
        pass
  observed, ok = _read_file(path)
  return ok and observed == raw


def write_enabled(params, enabled: bool, *, expected: bytes | None, root: Path | None = None,
                  authorized=None) -> bool:
  if type(enabled) is not bool or (authorized is not None and not authorized()):
    return False
  raw = b"1" if enabled else b"0"
  if registered(params):
    try:
      result = commit_exact(params, key=KEY, max_bytes=16, raw=raw, expected=expected,
                            authorized=authorized or (lambda: True), temp_prefix=".taco-tune-")
    except (OSError, TypeError, ValueError):
      return False
    return result.committed and result.verified
  return _write_file(_storage_root(root) / KEY, raw, expected)


class TurnSignalPreferences:
  def __init__(self, params, root: Path | None = None):
    self.params = params
    self.root = root
    self.enabled = True
    self.next_ns = 0
    self.last_ns = 0

  def sample(self, now_ns: int) -> bool:
    if now_ns < self.last_ns:
      self.next_ns = 0
    self.last_ns = now_ns
    if now_ns >= self.next_ns:
      self.next_ns = now_ns + _REFRESH_NS
      try:
        enabled, _raw, valid = read_enabled(self.params, root=self.root)
        self.enabled = enabled if valid else False
      except (OSError, TypeError, ValueError, OverflowError):
        self.enabled = False
    return self.enabled
