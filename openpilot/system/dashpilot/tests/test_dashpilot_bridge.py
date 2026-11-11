"""DashPilot's Comma source reads raw cereal bytes from ZMQ PUB sockets.

The port formula is the FNV-1a scheme in dashpilot bridge/msgq/impl_zmq.cc.
These expected ports were computed with that algorithm in 64-bit C.
"""

from pathlib import Path

import zmq

from openpilot.system.dashpilot.ports import service_port
from openpilot.system.dashpilot.preference import enabled, set_enabled
from openpilot.system.dashpilot.publish import PUBLISHED_SERVICES, open_publishers, send_payload


# 64-bit size_t FNV-1a, start 8023, span 65535-8023. Do not publish sendcan.
EXPECTED_PORTS = {
  "can": 62300,
  "selfdriveState": 9797,
  "selfdriveStateSP": 17252,
  "sendcan": 50650,
}


def test_ports_match_dashpilot_client():
  assert {name: service_port(name) for name in EXPECTED_PORTS} == EXPECTED_PORTS


def test_published_services_are_read_only():
  assert PUBLISHED_SERVICES == ("can", "selfdriveState")
  assert "sendcan" not in PUBLISHED_SERVICES
  assert "selfdriveStateSP" not in PUBLISHED_SERVICES


def test_missing_switch_is_on_and_only_zero_disables(tmp_path):
  path = tmp_path / "dashpilot-zmq"
  assert enabled(path) is True
  assert set_enabled(False, path) is True
  assert path.read_text() == "0"
  assert enabled(path) is False
  path.write_text("0\n")
  assert enabled(path) is False
  path.write_text("1")
  assert enabled(path) is True
  path.write_text("off")
  assert enabled(path) is True


def test_manager_registers_the_bridge_without_control_processes():
  source = Path(__file__).resolve().parents[2].joinpath("manager/process_config.py").read_text()
  assert 'PythonProcess("dashpilotd", "openpilot.system.dashpilot.bridge", dashpilot_zmq' in source
  assert "sendcan" not in source[source.index("def dashpilot_zmq") : source.index("def dashpilot_zmq") + 400]


def test_subscriber_receives_unmodified_capnp_bytes():
  context, sockets = open_publishers(PUBLISHED_SERVICES, bind_host="127.0.0.1")
  subs = []
  try:
    for name in PUBLISHED_SERVICES:
      sub = context.socket(zmq.SUB)
      sub.setsockopt(zmq.SUBSCRIBE, b"")
      sub.setsockopt(zmq.RCVTIMEO, 50)
      sub.connect(f"tcp://127.0.0.1:{service_port(name)}")
      subs.append((name, sub))

    payloads = {
      "can": b"\x00\x00\x00\x00\x05\x00\x00\x00can-bytes",
      "selfdriveState": bytes(range(32)),
    }
    pending = dict(payloads)
    deadline_attempts = 40
    for _ in range(deadline_attempts):
      for name, payload in payloads.items():
        assert send_payload(sockets[name], payload) is True
      for name, sub in subs:
        if name not in pending:
          continue
        try:
          got = sub.recv()
        except zmq.Again:
          continue
        assert got == pending[name]
        del pending[name]
      if not pending:
        break
    assert pending == {}
  finally:
    for _, sub in subs:
      sub.close(linger=0)
    for sock in sockets.values():
      sock.close(linger=0)
    context.term()
