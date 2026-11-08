"""Offline bench for competing k=0.75 floor readings.

selfdrive/controls/tests/test_lane_centering.py remains the regression check
for the unchanged Stable controller. Those tests do not validate a floor.
Nothing in this file is imported by controlsd or LaneCenteringController.

Training Lead reported, without supplying the log or a finished simulator run,
that about 75 percent less steering went away from an intended turn and that
the simulator did not complete the turns. This file does not reproduce that
report.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.drive_helpers import smooth_value
from openpilot.selfdrive.controls.lib.lane_centering import (
  LaneCenteringController,
  _MAX_GAIN,
  _MAX_RAW_CORRECTION,
  _SMOOTH_TAU,
)
from openpilot.selfdrive.controls.tests.lane_centering_model_path_floor_harness import (
  K,
  ONE_MINUS_K,
  CANDIDATES,
  OfflineFloorHarness,
  candidate_steady_delta,
  curvature_preservation_ratio,
  nominal_model_blend_weight,
  production_jerk_step,
  production_steady_delta,
)


_V = 20.0
_XS = np.linspace(0.0, 50.0, 52)


def _path(y, y_std=0.1):
  return SimpleNamespace(x=_XS.copy(), y=np.full_like(_XS, float(y)), yStd=np.full_like(_XS, float(y_std)))


def _model(left=-1.5, right=2.1, model_y=0.0, path_std=0.6, lane_prob=0.9):
  return SimpleNamespace(
    laneLines=[_path(0.0), _path(left), _path(right), _path(0.0)],
    laneLineProbs=[0.0, lane_prob, lane_prob, 0.0],
    laneLineStds=[0.0, 0.1, 0.1, 0.0],
    position=_path(model_y, path_std),
    meta=SimpleNamespace(laneChangeState=0),
  )


def _mirror(model):
  return _model(
    left=-model.laneLines[2].y[0],
    right=-model.laneLines[1].y[0],
    model_y=-model.position.y[0],
    path_std=model.position.yStd[0],
    lane_prob=model.laneLineProbs[1],
  )


def _steady(model, model_curvature=0.0, authority=0.0):
  controller = LaneCenteringController()
  output = 0.0
  for _ in range(2000):
    output = controller.update(model_curvature, model, _V, True, 0.0, authority, True, True)
  valid, raw = LaneCenteringController._raw_correction(model, _V, 0.0, authority)
  return output, raw, valid


def test_disabled_candidate_matches_baseline_including_abrupt_transitions():
  model = _model()
  for name in CANDIDATES:
    harness = OfflineFloorHarness(name)
    previous = None
    for frame, candidate_on in enumerate([False, False, True, True, False, False]):
      step = harness.step(0.01, model, _V, enabled=True, candidate_enabled=candidate_on)
      if not candidate_on:
        assert step.candidate == pytest.approx(step.baseline)
      if frame in (2, 4) and previous is not None:
        # Enable starts from the baseline correction. Disable returns to it on that frame.
        if not candidate_on:
          assert step.candidate == pytest.approx(step.baseline)
      previous = step


def test_enabled_first_step_uses_production_smoother_not_a_setpoint_jump():
  model = _model(left=0.0, right=3.6, path_std=0.6)
  _, raw, valid = _steady(model)
  assert valid
  target = candidate_steady_delta("gain_floor", raw, 0.0, True)
  harness = OfflineFloorHarness("gain_floor")
  held = harness.step(0.0, model, _V, enabled=True, candidate_enabled=False)
  assert held.candidate == pytest.approx(held.baseline)
  expected_first = float(smooth_value(target, held.baseline, _SMOOTH_TAU, dt=DT_CTRL))
  first = harness.step(0.0, model, _V, enabled=True, candidate_enabled=True)
  assert first.candidate == pytest.approx(expected_first)
  assert abs(first.candidate - held.baseline) < abs(target - held.baseline)
  assert abs(first.candidate) <= production_jerk_step(_V)


def test_unsaturated_nominal_weight_is_not_curvature_preservation():
  model = _model()
  output, raw, valid = _steady(model, model_curvature=0.0)
  assert valid
  delta = production_steady_delta(raw)
  assert output == pytest.approx(delta)
  assert abs(raw) < _MAX_RAW_CORRECTION
  weight = nominal_model_blend_weight(delta, raw)
  assert weight == pytest.approx(1.0 - _MAX_GAIN)
  assert weight < K
  assert curvature_preservation_ratio(output, 0.0) is None

  commanded, raw_with_model, _ = _steady(model, model_curvature=0.002)
  assert raw_with_model == pytest.approx(raw)
  preservation = curvature_preservation_ratio(commanded, 0.002)
  assert preservation == pytest.approx((0.002 + delta) / 0.002)
  assert preservation != pytest.approx(weight)


def test_candidates_disagree_and_each_keeps_its_own_equation():
  model = _model(left=0.0, right=3.6, path_std=0.6)
  _, raw, valid = _steady(model)
  assert valid
  assert abs(raw) > _MAX_RAW_CORRECTION
  baseline = production_steady_delta(raw)
  assert baseline == pytest.approx(_MAX_RAW_CORRECTION * _MAX_GAIN)

  deltas = {name: candidate_steady_delta(name, raw, -0.002, True) for name in CANDIDATES}
  assert len(set(np.round(list(deltas.values()), 12))) == len(CANDIDATES)
  assert deltas["gain_floor"] == pytest.approx(_MAX_RAW_CORRECTION * min(_MAX_GAIN, ONE_MINUS_K))
  assert deltas["pre_gain_scale"] == pytest.approx(production_steady_delta(raw * ONE_MINUS_K))
  assert deltas["scale_post_clamp_by_k"] == pytest.approx(baseline * K)
  assert deltas["scale_post_clamp_by_one_minus_k"] == pytest.approx(baseline * ONE_MINUS_K)
  oppose_limit = ONE_MINUS_K * 0.002
  assert deltas["opposing_curvature_floor"] == pytest.approx(np.copysign(oppose_limit, baseline))
  for delta in deltas.values():
    assert abs(delta) <= abs(baseline) + 1e-12


def test_opposing_floor_binds_only_against_the_model_and_preserves_sign():
  raw = 0.01
  model_curvature = -0.002
  baseline = production_steady_delta(raw)
  opposed = candidate_steady_delta("opposing_curvature_floor", raw, model_curvature, True)
  same = candidate_steady_delta("opposing_curvature_floor", raw, -model_curvature, True)
  assert same == pytest.approx(baseline)
  command = model_curvature + opposed
  assert command * model_curvature > 0.0
  assert curvature_preservation_ratio(command, model_curvature) == pytest.approx(K)
  assert nominal_model_blend_weight(opposed, raw) != pytest.approx(K)


def test_left_right_mirror_negates_baseline_and_every_candidate():
  model = _model()
  mirrored = _mirror(model)
  _, raw, valid = _steady(model, model_curvature=0.0015)
  _, raw_mirror, valid_mirror = _steady(mirrored, model_curvature=-0.0015)
  assert valid and valid_mirror
  assert raw_mirror == pytest.approx(-raw)
  for name in CANDIDATES:
    assert candidate_steady_delta(name, raw_mirror, -0.0015, True) == pytest.approx(
      -candidate_steady_delta(name, raw, 0.0015, True)
    )


def test_near_zero_and_zero_model_paths():
  raw = 0.003
  near = candidate_steady_delta("opposing_curvature_floor", raw, -1e-6, True)
  command = -1e-6 + near
  assert curvature_preservation_ratio(command, -1e-6) == pytest.approx(K, rel=1e-6)
  zero = candidate_steady_delta("opposing_curvature_floor", raw, 0.0, True)
  assert zero == pytest.approx(production_steady_delta(raw))
  assert curvature_preservation_ratio(zero, 0.0) is None
  assert nominal_model_blend_weight(production_steady_delta(0.0), 0.0) is None


def test_deadband_and_raw_clamp_are_discontinuous_in_the_baseline():
  inside = _model(left=-1.75, right=1.85, path_std=0.6)
  outside = _model(left=-1.5, right=2.1, path_std=0.6)
  _, raw_inside, valid_inside = _steady(inside)
  _, raw_outside, valid_outside = _steady(outside)
  assert valid_inside and valid_outside
  assert raw_inside == pytest.approx(0.0)
  assert raw_outside > 0.0
  saturated = _model(left=0.0, right=3.6, path_std=0.6)
  _, raw_saturated, _ = _steady(saturated)
  assert production_steady_delta(raw_saturated) == pytest.approx(_MAX_RAW_CORRECTION * _MAX_GAIN)
  assert production_steady_delta(raw_saturated + 1.0) == pytest.approx(_MAX_RAW_CORRECTION * _MAX_GAIN)


def test_invalid_inputs_follow_the_controller_and_do_not_invent_a_correction():
  model = _model()
  harness = OfflineFloorHarness("gain_floor")
  for bad in (np.nan, np.inf):
    step = harness.step(0.01, model, _V, enabled=True, authority=bad, candidate_enabled=True)
    assert step.candidate == pytest.approx(step.baseline)
  unqualified = _model(lane_prob=0.1)
  valid, _ = LaneCenteringController._raw_correction(unqualified, _V, 0.0, 0.0)
  assert not valid
  faded = harness.step(0.02, unqualified, _V, enabled=True, candidate_enabled=True)
  assert faded.candidate == pytest.approx(faded.baseline)
  gated = harness.step(0.02, model, _V, enabled=False, candidate_enabled=True)
  assert gated.candidate == pytest.approx(gated.baseline)
  assert gated.baseline == pytest.approx(0.02)


def test_downstream_jerk_clamp_still_sits_outside_this_harness():
  steady = _MAX_RAW_CORRECTION * _MAX_GAIN
  unsmoothed = production_jerk_step(_V)
  assert steady > unsmoothed
  smoothed = abs(float(smooth_value(steady, 0.0, _SMOOTH_TAU, dt=DT_CTRL)))
  assert smoothed < unsmoothed


@pytest.mark.parametrize("name", CANDIDATES)
def test_candidate_names_are_explicit(name):
  assert candidate_steady_delta(name, 0.001, 0.0, False) == pytest.approx(production_steady_delta(0.001))
