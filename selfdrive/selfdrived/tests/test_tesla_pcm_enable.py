import importlib.util
import sys
import types
from pathlib import Path

from opendbc.car import structs

from openpilot.selfdrive.car.cruise_state import should_cancel_stock_cruise


def _load_state_machine():
  """Load the real state machine without the aarch64 messaging extension."""
  events = types.ModuleType("openpilot.selfdrive.selfdrived.events")

  class ET:
    ENABLE = "enable"
    PRE_ENABLE = "preEnable"
    OVERRIDE_LATERAL = "overrideLateral"
    OVERRIDE_LONGITUDINAL = "overrideLongitudinal"
    NO_ENTRY = "noEntry"
    WARNING = "warning"
    USER_DISABLE = "userDisable"
    SOFT_DISABLE = "softDisable"
    IMMEDIATE_DISABLE = "immediateDisable"
    PERMANENT = "permanent"

  class Events:
    def __init__(self, event_types=()):
      self.event_types = set(event_types)

    def contains(self, event_type: str) -> bool:
      return event_type in self.event_types

  events.ET = ET
  events.Events = Events

  utilities = types.ModuleType("openpilot.starpilot.common.starpilot_utilities")

  def contains_event_type(openpilot_events, starpilot_events, *event_types):
    return any(openpilot_events.contains(event_type) or starpilot_events.contains(event_type)
               for event_type in event_types)

  utilities.contains_event_type = contains_event_type

  realtime = types.ModuleType("openpilot.common.realtime")
  realtime.DT_CTRL = 0.01

  stubs = {
    "openpilot.selfdrive.selfdrived.events": events,
    "openpilot.starpilot.common.starpilot_utilities": utilities,
    "openpilot.common.realtime": realtime,
  }
  saved = {name: sys.modules.get(name) for name in stubs}
  sys.modules.update(stubs)
  try:
    spec = importlib.util.spec_from_file_location(
      "isolated_selfdrive_state_for_pcm_enable",
      Path(__file__).resolve().parents[1] / "state.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
  finally:
    for name, previous in saved.items():
      if previous is None:
        sys.modules.pop(name, None)
      else:
        sys.modules[name] = previous
  module.ET = ET
  module._Events = Events
  return module


STATE = _load_state_machine()
ET = STATE.ET
Events = STATE._Events
State = STATE.State


def _step(machine, openpilot_types=(), starpilot_types=(), always_on_lateral=False):
  enabled, active = machine.update(Events(openpilot_types), Events(starpilot_types), always_on_lateral)
  return machine.state, enabled, active


def _tesla_params():
  cp = structs.CarParams.new_message()
  cp.brand = "tesla"
  cp.pcmCruise = True
  cp.openpilotLongitudinalControl = True
  return cp


def test_pcm_enable_with_gas_override_engages_and_does_not_cancel():
  # Route 00000013--baab9e2ec5 at t=63.2: pcmEnable + gasPressedOverride, no no-entry.
  machine = STATE.StateMachine()
  state, enabled, active = _step(machine, (ET.ENABLE, ET.OVERRIDE_LONGITUDINAL))

  assert state == State.overriding
  assert enabled
  assert active
  assert not should_cancel_stock_cruise(_tesla_params(), cruise_enabled=True, controls_enabled=enabled)


def test_pcm_enable_alone_engages_and_keeps_stock_cruise():
  machine = STATE.StateMachine()
  state, enabled, _active = _step(machine, (ET.ENABLE,))

  assert state == State.enabled
  assert enabled
  assert not should_cancel_stock_cruise(_tesla_params(), cruise_enabled=True, controls_enabled=enabled)


def test_disabled_pcm_cruise_still_cancels_stock_cruise():
  assert should_cancel_stock_cruise(_tesla_params(), cruise_enabled=True, controls_enabled=False)
  assert not should_cancel_stock_cruise(_tesla_params(), cruise_enabled=False, controls_enabled=False)


def test_gas_override_without_enable_stays_disabled():
  machine = STATE.StateMachine()
  state, enabled, _active = _step(machine, (ET.OVERRIDE_LONGITUDINAL,))

  assert state == State.disabled
  assert not enabled


def test_releasing_gas_returns_from_overriding_to_enabled():
  machine = STATE.StateMachine()
  _step(machine, (ET.ENABLE, ET.OVERRIDE_LONGITUDINAL))
  state, enabled, active = _step(machine, ())

  assert state == State.enabled
  assert enabled
  assert active


def test_pcm_disable_cancels_from_overriding_and_enabled():
  machine = STATE.StateMachine()
  _step(machine, (ET.ENABLE, ET.OVERRIDE_LONGITUDINAL))
  state, enabled, _active = _step(machine, (ET.USER_DISABLE, ET.OVERRIDE_LONGITUDINAL))
  assert state == State.disabled
  assert not enabled

  _step(machine, (ET.ENABLE,))
  state, enabled, _active = _step(machine, (ET.USER_DISABLE,))
  assert state == State.disabled
  assert not enabled
  assert should_cancel_stock_cruise(_tesla_params(), cruise_enabled=True, controls_enabled=enabled)


def test_no_entry_blocks_pcm_enable_including_starpilot_crash_latch():
  blocked = (
    (ET.NO_ENTRY,),
    (ET.NO_ENTRY, ET.USER_DISABLE),  # wrongCarMode
    (ET.NO_ENTRY, ET.SOFT_DISABLE),  # wrongGear
    (ET.NO_ENTRY, ET.IMMEDIATE_DISABLE),  # controlsMismatch
    (ET.NO_ENTRY, ET.USER_DISABLE, ET.PERMANENT),  # reverseGear
  )
  for openpilot_types in blocked:
    machine = STATE.StateMachine()
    state, enabled, _active = _step(machine, (ET.ENABLE, ET.OVERRIDE_LONGITUDINAL, *openpilot_types))
    assert state == State.disabled
    assert not enabled
    assert ET.NO_ENTRY in machine.current_alert_types
    assert should_cancel_stock_cruise(_tesla_params(), cruise_enabled=True, controls_enabled=enabled)

  machine = STATE.StateMachine()
  state, enabled, _active = _step(
    machine,
    (ET.ENABLE, ET.OVERRIDE_LONGITUDINAL),
    starpilot_types=(ET.NO_ENTRY, ET.IMMEDIATE_DISABLE),
  )
  assert state == State.disabled
  assert not enabled
  assert ET.NO_ENTRY in machine.current_alert_types


def test_pre_enable_engages_without_cancelling_pcm_cruise():
  machine = STATE.StateMachine()
  state, enabled, active = _step(machine, (ET.ENABLE, ET.PRE_ENABLE))

  assert state == State.preEnabled
  assert enabled
  assert not active
  assert not should_cancel_stock_cruise(_tesla_params(), cruise_enabled=True, controls_enabled=enabled)
