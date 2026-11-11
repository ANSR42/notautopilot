"""ZMQ PUB sockets in the shape DashPilot's Comma source subscribes to.

DashPilot opens ZMQ_SUB, subscribes to every frame, and treats the frame
body as a flat capnp cereal Event. There is no topic prefix. can is the
received vehicle bus. selfdriveState is the read-only engagement message
the app uses for the cruise indicator and lane-change warning.
selfdriveStateSP is a sunnypilot message this fork does not have, so it is
not published; the app's subscription to it simply stays empty.

sendcan is the actuation bus and is not published.
"""

import zmq

from openpilot.system.dashpilot.ports import service_port


# High-water mark in messages. can is 100 Hz; 64 keeps a short burst and
# drops the rest instead of buffering tens of megabytes on the comma.
SNDHWM = 64

PUBLISHED_SERVICES = ("can", "selfdriveState")


def open_publishers(services=PUBLISHED_SERVICES, bind_host="0.0.0.0"):
  context = zmq.Context()
  sockets = {}
  for name in services:
    if name == "sendcan":
      raise ValueError("refusing to publish the actuation bus")
    sock = context.socket(zmq.PUB)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.SNDHWM, SNDHWM)
    sock.bind(f"tcp://{bind_host}:{service_port(name)}")
    sockets[name] = sock
  return context, sockets


def send_payload(sock, payload: bytes) -> bool:
  try:
    sock.send(payload, flags=zmq.NOBLOCK, copy=True)
    return True
  except zmq.Again:
    return False
