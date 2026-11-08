"""Offline-only comparisons for a k=0.75 model-path floor.

This module is a bench harness. controlsd and LaneCenteringController do not
import it, and nothing here is a vehicle toggle. Each candidate is a reading of
the same requested floor, not a selected steering law.

Stable lane centering, selfdrive/controls/lib/lane_centering.py, at the
StarPilot base:

  lookahead_m = clip(v_ego_m_s, 8, 35)
  error_m = target_y_m - model_y_m
  positive y and positive curvature are to the right
  error_m is reduced by the 0.08 m deadband, then optionally by E2E authority
  raw_1_per_m = 2 * error_m / lookahead_m**2
  steady_delta_1_per_m = clip(raw, ±0.004) * 0.30
  command_1_per_m = model_curvature_1_per_m + smooth(steady_delta, tau=0.4 s)

The constant-curvature identity y = curvature * lookahead**2 / 2 makes an
unsaturated, unclipped correction a lane blend weight:

  nominal_model_weight = 1 - steady_delta / raw

With gain 0.30 and no E2E reduction and no clip, that nominal weight is 0.70.
That is not the fraction of model curvature preserved in the command.
Preservation is command / model_curvature, and it is undefined at zero model
curvature. A clip, a deadband, E2E scaling, or a model curvature that is not
2*model_y/lookahead**2 makes those two numbers differ.

k = 0.75 means "keep at least 75 percent of the model contribution." These
readings are all tested because that sentence does not pick a unique equation:

  gain_floor
    Use min(0.30, 1-k) = 0.25 as the gain. Unsaturated nominal model weight
    becomes 0.75. The raw ±0.004 clamp is unchanged.
  pre_gain_scale
    Multiply raw by 1-k = 0.25, then apply the existing ±0.004 clamp and 0.30
    gain. Unsaturated nominal model weight becomes 0.925.
  opposing_curvature_floor
    After the production clamp and gain, if the correction sign opposes the
    model curvature, limit its magnitude to (1-k)*|model_curvature|. The
    command then keeps the model sign and at least 75 percent of its
    magnitude. Same-direction corrections are unchanged. A zero model
    curvature has no magnitude to preserve, so this reading does not bind.
  scale_post_clamp_by_k
    Multiply the production steady correction by k = 0.75. This keeps 75
    percent of the lane correction, which is not a 75 percent model floor.
  scale_post_clamp_by_one_minus_k
    Multiply the production steady correction by 1-k = 0.25. This is the
    post-clamp cousin of pre_gain_scale; they differ once the ±0.004 clamp
    binds.

Disabled means the candidate correction is the production correction on that
same frame, including the frame the candidate is switched off.
"""

from dataclasses import dataclass

import numpy as np

from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.drive_helpers import clip_curvature, smooth_value
from openpilot.selfdrive.controls.lib.lane_centering import (
  LaneCenteringController,
  _MAX_GAIN,
  _MAX_RAW_CORRECTION,
  _MIN_V_EGO,
  _SMOOTH_TAU,
)


K = 0.75
ONE_MINUS_K = 1.0 - K

CANDIDATES = (
  "gain_floor",
  "pre_gain_scale",
  "opposing_curvature_floor",
  "scale_post_clamp_by_k",
  "scale_post_clamp_by_one_minus_k",
)


def production_steady_delta(raw: float) -> float:
  """Additive curvature, 1/m, after the production raw clamp and gain."""
  if not np.isfinite(raw):
    return float("nan")
  return float(np.clip(raw, -_MAX_RAW_CORRECTION, _MAX_RAW_CORRECTION)) * _MAX_GAIN


def candidate_steady_delta(name: str, raw: float, model_curvature: float, enabled: bool) -> float:
  """Return one candidate's steady additive correction, or the baseline if disabled."""
  baseline = production_steady_delta(raw)
  if not enabled or name == "baseline":
    return baseline
  if not np.isfinite(baseline) or not np.isfinite(model_curvature):
    return baseline
  if name == "gain_floor":
    gain = min(_MAX_GAIN, ONE_MINUS_K)
    return float(np.clip(raw, -_MAX_RAW_CORRECTION, _MAX_RAW_CORRECTION)) * gain
  if name == "pre_gain_scale":
    return production_steady_delta(raw * ONE_MINUS_K)
  if name == "opposing_curvature_floor":
    if baseline * model_curvature >= 0.0:
      return baseline
    oppose_limit = ONE_MINUS_K * abs(model_curvature)
    return float(np.copysign(min(abs(baseline), oppose_limit), baseline))
  if name == "scale_post_clamp_by_k":
    return baseline * K
  if name == "scale_post_clamp_by_one_minus_k":
    return baseline * ONE_MINUS_K
  raise KeyError(name)


def nominal_model_blend_weight(delta: float, raw: float) -> float | None:
  """1 - delta/raw under the constant-curvature identity. None if raw is ~0 or non-finite."""
  if not np.isfinite(delta) or not np.isfinite(raw) or abs(raw) < 1e-12:
    return None
  return float(1.0 - delta / raw)


def curvature_preservation_ratio(command: float, model_curvature: float) -> float | None:
  """command/model_curvature. None when the model curvature is ~0 or non-finite."""
  if not np.isfinite(command) or not np.isfinite(model_curvature) or abs(model_curvature) < 1e-9:
    return None
  return float(command / model_curvature)


def production_jerk_step(v_ego: float) -> float:
  """One controlsd clip_curvature step at this speed, 1/m, roll 0 and jerk factor 1."""
  limited, _ = clip_curvature(v_ego, 0.0, 1.0, 0.0)
  return abs(float(limited))


@dataclass
class HarnessStep:
  baseline: float
  candidate: float
  raw: float | None
  raw_valid: bool
  candidate_enabled: bool


class OfflineFloorHarness:
  """Step the real controller and a side-by-side candidate filter.

  The candidate filter uses the production smooth_value and tau. It is not
  written back into the controller. While disabled, the returned candidate
  command equals the controller command.
  """

  def __init__(self, name: str) -> None:
    if name not in CANDIDATES:
      raise KeyError(name)
    self.name = name
    self.controller = LaneCenteringController()
    self._candidate_correction = 0.0

  def reset(self) -> None:
    self.controller.reset()
    self._candidate_correction = 0.0

  def step(self, model_curvature: float, model_v2, v_ego: float, *, enabled: bool, offset: float = 0.0,
           authority: float = 0.0, lat_active: bool = True, model_valid: bool = True,
           candidate_enabled: bool = False) -> HarnessStep:
    baseline = self.controller.update(
      model_curvature, model_v2, v_ego, enabled, offset, authority, lat_active, model_valid,
    )
    hard_gate = (not enabled or not lat_active or not model_valid or
                 not np.isfinite(v_ego) or float(v_ego) < _MIN_V_EGO)
    if not candidate_enabled or hard_gate:
      self._candidate_correction = self.controller._correction
      return HarnessStep(baseline, baseline, None, False, False)

    try:
      curvature = float(model_curvature)
    except (TypeError, ValueError):
      self._candidate_correction = self.controller._correction
      return HarnessStep(baseline, baseline, None, False, True)

    valid, raw = LaneCenteringController._raw_correction(
      model_v2, float(v_ego), float(offset), float(authority),
    ) if np.isfinite(v_ego) and np.isfinite(offset) and np.isfinite(authority) else (False, 0.0)
    if not valid or not np.isfinite(raw) or not np.isfinite(curvature):
      self._candidate_correction = self.controller._correction
      return HarnessStep(baseline, baseline, None if not valid else raw, False, True)

    target = candidate_steady_delta(self.name, raw, curvature, True)
    self._candidate_correction = float(smooth_value(
      target, self._candidate_correction, _SMOOTH_TAU, dt=DT_CTRL,
    ))
    return HarnessStep(baseline, curvature + self._candidate_correction, raw, True, True)
