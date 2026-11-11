"""TCP ports DashPilot uses for comma service names.

dashpilot-android connects with check_endpoint=true, which is the FNV-1a
mapping in bridge/msgq/impl_zmq.cc: port = 8023 + (hash % (65535 - 8023)).
The hash is 64-bit, matching a comma four (and the phone) size_t.
"""

_FNV_PRIME = 0x100000001B3
_FNV_OFFSET = 0xCBF29CE484222325
_MASK = 0xFFFFFFFFFFFFFFFF
_START_PORT = 8023
_PORT_SPAN = 65535 - _START_PORT


def service_port(name: str) -> int:
  digest = _FNV_OFFSET
  for byte in name.encode("ascii"):
    digest ^= byte
    digest = (digest * _FNV_PRIME) & _MASK
  return _START_PORT + (digest % _PORT_SPAN)
