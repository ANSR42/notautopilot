#!/usr/bin/env python3
"""Republish local msgq services on the ZMQ ports DashPilot already uses.

This process only reads msgq and writes ZMQ. It does not open sendcan and
does not publish back onto the car, panda, or control buses.

CPU: can and selfdriveState are each 100 Hz. The work is one nonblocking
read of those two sockets and a copy onto TCP, with a 10 ms sleep when both
are empty. While driving that is expected to be a few percent of one core.
This is an estimate from the message rates, not a measurement on a comma four.
"""

import signal
import time

from openpilot.system.dashpilot.preference import enabled
from openpilot.system.dashpilot.publish import PUBLISHED_SERVICES, open_publishers, send_payload


def main() -> None:
  if not enabled():
    return

  import openpilot.cereal.messaging as messaging
  from openpilot.common.swaglog import cloudlog
  from openpilot.system.dashpilot.ports import service_port

  stop = False

  def request_stop(_sig, _frame):
    nonlocal stop
    stop = True

  signal.signal(signal.SIGINT, request_stop)
  signal.signal(signal.SIGTERM, request_stop)

  context, publishers = open_publishers(PUBLISHED_SERVICES)
  subscribers = []
  try:
    pending = list(PUBLISHED_SERVICES)
    logged = False
    dropped = 0
    while not stop:
      if pending:
        still_pending = []
        for name in pending:
          try:
            subscribers.append((messaging.sub_sock(name, conflate=False), name))
          except messaging.IpcError:
            still_pending.append(name)
        pending = still_pending
        if subscribers and not logged:
          cloudlog.info("dashpilot zmq bridge on %s", {name: service_port(name) for name in PUBLISHED_SERVICES})
          logged = True
      got = False
      for sock, name in subscribers:
        for raw in messaging.drain_sock_raw(sock):
          got = True
          if not send_payload(publishers[name], raw):
            dropped += 1
            if dropped == 1 or dropped % 1000 == 0:
              cloudlog.warning("dashpilot zmq bridge dropped %s payloads", dropped)
      if not got or pending:
        time.sleep(0.2 if pending else 0.01)
  finally:
    for sock in publishers.values():
      sock.close(linger=0)
    context.term()


if __name__ == "__main__":
  main()
