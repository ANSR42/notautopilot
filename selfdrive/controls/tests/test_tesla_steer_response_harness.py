"""Angle-space stage checks. Not a road test, not a log replay, and not vehicle validation."""

from dataclasses import fields
from pathlib import Path

from opendbc.car import ACCELERATION_DUE_TO_GRAVITY, DT_CTRL, STD_CARGO_KG
from opendbc.car.lateral import ISO_LATERAL_ACCEL, apply_steer_angle_limits_vm, get_max_angle_delta_vm, get_max_angle_vm
from opendbc.car.tesla.carcontroller import get_safety_CP
from opendbc.car.tesla.values import CAR, CarControllerParams
from opendbc.car.vehicle_model import VehicleModel
from openpilot.selfdrive.controls.tests.tesla_steer_response_harness import (
  BINDER_ACCEL_MAX_ANGLE,
  BINDER_JERK_DELTA,
  BINDER_MAX_ANGLE_RATE,
  BINDER_NAMES,
  BINDER_NONE,
  INVESTIGATION_LABEL,
  SPEEDS_M_S,
  classify_first_binder,
  command_dt_s,
  latcontrol_angle_desired_deg,
  model_y_uses_cooperative_steering,
  model_y_vehicle_model,
  steer_response,
  steer_response_grid,
  tighter_delta_binder,
)


_REPO = Path(__file__).resolve().parents[3]
_PRODUCTION = (
  "selfdrive/controls/controlsd.py",
  "selfdrive/controls/lib/desire_helper.py",
  "selfdrive/controls/lib/lane_centering.py",
  "selfdrive/controls/lib/latcontrol_angle.py",
  "opendbc_repo/opendbc/car/tesla/carcontroller.py",
)


def test_limits_match_the_live_tesla_sources():
  limits = CarControllerParams.ANGLE_LIMITS
  road_roll = 0.06
  assert limits.MAX_LATERAL_ACCEL == ISO_LATERAL_ACCEL + ACCELERATION_DUE_TO_GRAVITY * road_roll
  assert limits.MAX_LATERAL_JERK == 3.0 + ACCELERATION_DUE_TO_GRAVITY * road_roll
  assert limits.MAX_ANGLE_RATE == 5
  assert limits.STEER_ANGLE_MAX == 360
  assert CarControllerParams.STEER_STEP == 2
  assert command_dt_s() == DT_CTRL * 2
  assert abs(1.0 / command_dt_s() - 50.0) < 1e-9

  specs = CAR.TESLA_MODEL_Y.config.specs
  assert specs.mass == 2072.0
  assert specs.wheelbase == 2.890
  assert specs.steerRatio == 12.0

  cp = get_safety_CP()
  assert cp.carFingerprint == CAR.TESLA_MODEL_Y
  assert cp.brand == "tesla"
  assert cp.mass == specs.mass + STD_CARGO_KG
  # Capnp stores wheelbase at lower precision than the Python spec literal.
  assert abs(cp.wheelbase - specs.wheelbase) < 1e-5
  assert cp.steerRatio == specs.steerRatio
  vm = model_y_vehicle_model()
  assert isinstance(vm, VehicleModel)
  assert vm.m == cp.mass
  assert vm.l == cp.wheelbase
  assert vm.sR == cp.steerRatio


def test_source_text_keeps_the_tesla_angle_path_and_model_3_coop_gate():
  angle = (_REPO / "selfdrive/controls/lib/latcontrol_angle.py").read_text(encoding="utf-8")
  assert 'self.use_steer_limited_by_safety = CP.brand in ("tesla", "hyundai")' in angle
  assert "VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll)" in angle
  assert "angle_steers_des += params.angleOffsetDeg" in angle

  controller = (_REPO / "opendbc_repo/opendbc/car/tesla/carcontroller.py").read_text(encoding="utf-8")
  assert "return CarInterface.get_non_essential_params(CAR.TESLA_MODEL_Y)" in controller
  assert "self.coop_enabled = CP.carFingerprint == CAR.TESLA_MODEL_3" in controller
  assert "self.VM = VehicleModel(get_safety_CP())" in controller
  assert "if self.frame % 2 == 0:" in controller
  assert "apply_steer_angle_limits_vm(" in controller
  assert model_y_uses_cooperative_steering() is False

  lateral = (_REPO / "opendbc_repo/opendbc/car/lateral.py").read_text(encoding="utf-8")
  assert "def get_max_angle_delta_vm(" in lateral
  assert "def get_max_angle_vm(" in lateral
  assert "max_angle_delta = min(max_angle_delta, limits.ANGLE_LIMITS.MAX_ANGLE_RATE)" in lateral


def test_stage_fields_exist_and_the_label_stays_investigative():
  report = steer_response(13.9, frames=5)
  names = {item.name for item in fields(report)}
  for required in (
    "label",
    "speed_m_s",
    "model_curvature_1_per_m",
    "requested_curvature_1_per_m",
    "desired_angle_deg",
    "jerk_delta_deg",
    "max_angle_rate_deg",
    "accel_max_angle_deg",
    "steps",
    "time_to_90pct_s",
    "reached_90pct",
    "final_angle_deg",
    "cooperative_steering_active",
  ):
    assert required in names
  step_names = {item.name for item in fields(report.steps[0])}
  assert {"frame", "time_s", "angle_deg", "first_binder", "accel_clip_applied"} <= step_names
  assert report.label == INVESTIGATION_LABEL
  assert "not a completed turn" in report.label
  assert "not a log replay" in report.label
  assert "not proof of Mike's intervention cause" in report.label
  assert report.cooperative_steering_active is False
  assert report.roll_rad == 0.0
  assert report.angle_offset_deg == 0.0
  assert report.blinker is True


def test_binder_names_are_mutually_exclusive_and_each_one_can_be_first():
  assert BINDER_NAMES == {BINDER_JERK_DELTA, BINDER_MAX_ANGLE_RATE, BINDER_ACCEL_MAX_ANGLE, BINDER_NONE}
  assert len(BINDER_NAMES) == 4
  assert tighter_delta_binder(5.0, 5.0) == BINDER_JERK_DELTA
  assert tighter_delta_binder(4.0, 5.0) == BINDER_JERK_DELTA
  assert tighter_delta_binder(6.0, 5.0) == BINDER_MAX_ANGLE_RATE

  vm = model_y_vehicle_model()
  rate_binder, rate_clip, _ = classify_first_binder(100.0, 0.0, 5.0, vm)
  jerk_binder, _, _ = classify_first_binder(100.0, 0.0, 13.9, vm)
  none_binder, none_clip, held = classify_first_binder(12.0, 12.0, 8.0, vm)
  # Inside the jerk window, just past the accel max angle, so only the accel clip binds.
  accel_binder, accel_clip, accel_angle = classify_first_binder(41.2, 40.5, 13.9, vm)

  assert rate_binder == BINDER_MAX_ANGLE_RATE
  assert jerk_binder == BINDER_JERK_DELTA
  assert none_binder == BINDER_NONE and none_clip is False and held == 12.0
  assert accel_binder == BINDER_ACCEL_MAX_ANGLE and accel_clip is True
  assert accel_angle == get_max_angle_vm(13.9, vm, CarControllerParams)
  assert {rate_binder, jerk_binder, none_binder, accel_binder} == BINDER_NAMES
  assert rate_clip is False


def test_open_loop_steps_match_apply_steer_angle_limits_vm_and_one_binder():
  reports = steer_response_grid(frames=30)
  assert tuple(report.speed_m_s for report in reports) == SPEEDS_M_S
  vm = model_y_vehicle_model()
  for report in reports:
    assert report.model_curvature_1_per_m < 0.0
    assert report.requested_curvature_1_per_m < 0.0
    assert report.desired_angle_deg > 0.0
    replay = 0.0
    seen = set()
    for step in report.steps:
      replay = apply_steer_angle_limits_vm(
        report.desired_angle_deg,
        replay,
        report.speed_m_s,
        0.0,
        True,
        CarControllerParams,
        vm,
      )
      assert step.angle_deg == replay
      assert step.first_binder in BINDER_NAMES
      assert isinstance(step.first_binder, str)
      seen.add(step.first_binder)
    assert len(seen) >= 1
    direct = latcontrol_angle_desired_deg(report.requested_curvature_1_per_m, report.speed_m_s, vm, roll=0.0, angle_offset_deg=0.0)
    assert report.desired_angle_deg == direct
    assert report.jerk_delta_deg == get_max_angle_delta_vm(report.speed_m_s, vm, CarControllerParams)
    assert report.accel_max_angle_deg == get_max_angle_vm(report.speed_m_s, vm, CarControllerParams)


def test_five_meters_per_second_is_rate_limited_and_still_reaches_ninety_percent():
  report = steer_response(5.0, frames=40)
  assert report.jerk_delta_deg > report.max_angle_rate_deg
  assert not report.curvature_cap_widens_radius
  assert report.steps[0].first_binder == BINDER_MAX_ANGLE_RATE
  assert report.steps[0].accel_clip_applied is False
  assert report.reached_90pct
  assert report.time_to_90pct_s == 19 * report.dt_s
  assert abs(report.final_angle_deg - report.desired_angle_deg) < 1e-6


def test_route_speed_jerk_arrives_first_and_the_accel_limit_blocks_ninety_percent():
  report = steer_response(13.9)
  assert report.curvature_cap_widens_radius
  assert report.jerk_delta_deg < report.max_angle_rate_deg
  assert report.desired_angle_deg > report.accel_max_angle_deg
  assert 0.9 * report.desired_angle_deg > report.accel_max_angle_deg
  assert report.steps[0].first_binder == BINDER_JERK_DELTA
  assert report.reached_90pct is False
  assert report.time_to_90pct_s is None
  assert abs(report.final_angle_deg - report.accel_max_angle_deg) < 1e-4
  assert any(step.accel_clip_applied and step.first_binder == BINDER_JERK_DELTA for step in report.steps)


def test_harness_is_not_imported_by_the_controllers():
  for relative in _PRODUCTION:
    text = (_REPO / relative).read_text(encoding="utf-8")
    assert "tesla_steer_response_harness" not in text
