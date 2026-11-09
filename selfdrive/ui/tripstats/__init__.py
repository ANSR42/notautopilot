# Ported from TeslaPilot (MIT), Memberoffoxhound/TeslaPilot, branch Highland-Dev.
# https://github.com/Memberoffoxhound/TeslaPilot
# Stats stay in one local JSON file. Nothing is uploaded.

"""Trip stats recorder. Day and week use the device clock's local time zone."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from openpilot.common.time_helpers import system_time_valid
from openpilot.selfdrive.ui.tripstats import store
from openpilot.selfdrive.ui.tripstats.card import eligible
from openpilot.selfdrive.ui.tripstats.recorder import MOVING_V, DriveRecorder

SHOW_S = 20.0
SAVE_S = 30.0

live = DriveRecorder()
_data: dict | None = None
_held: list[dict] = []
_saved_t = 0.0
_path: Path | None = None
_logged = False


def configure(path: Path | None) -> None:
  """Tests point the store at a temp file. None uses the device file."""
  global _path, _data, _held
  _path = path
  _data = None
  _held = []


def reset() -> None:
  global live, _data, _held, _saved_t, _logged
  live = DriveRecorder()
  _data = None
  _held = []
  _saved_t = 0.0
  _logged = False


def _file() -> Path:
  return _path if _path is not None else store.default_path()


def wall_now() -> float:
  return datetime.now().timestamp()


def _store() -> dict:
  global _data, _held
  if _data is None:
    data = store.read_file(_file())
    opens = data.pop("open")
    _held = [d for d in opens if not d["ok"]]
    for d in opens:
      if d["ok"]:
        data = store.add_drive(data, d)
    _data = data
    if len(_held) < len(opens):
      _save()
  return _data


def _open() -> list[dict]:
  return _held + ([live.summary(wall_now())] if live.active else [])


def view(drive: dict | None = None) -> dict:
  if drive is None:
    return store.view(_store(), _open(), datetime.fromtimestamp(wall_now(), UTC), None, 6)
  from datetime import timedelta, timezone
  zone = timezone(timedelta(seconds=drive["off"]))
  return store.view(_store(), (), datetime.fromtimestamp(drive["end"], UTC), zone, 6)


def due_summary(rec: DriveRecorder | None = None) -> dict | None:
  rec = live if rec is None else rec
  if not rec.active or rec.last_v > MOVING_V:
    return None
  drive = rec.summary(wall_now())
  return drive if eligible(drive) else None


def missed_trip() -> dict | None:
  last = _store().get("last")
  return last if last and not last.get("shown") and eligible(last) else None


def mark_shown(drive: dict | None = None) -> None:
  global _data
  try:
    if drive is None:
      live.shown = True
    elif drive is _store().get("last"):
      _data = {**_data, "last": {**drive, "shown": True}}
    _save()
  except Exception:
    pass


def _save() -> None:
  global _saved_t
  _saved_t = time.monotonic()
  w, ok = wall_now(), system_time_valid()
  store.write_file(_file(), {**_store(), "open": [store.stamp(d, w, None, ok) for d in _open()]})


def tick(started: bool, now: float, v_ego: float, enabled: bool, state: str = "",
         alert_status: str = "normal", alert_type: str = "", drive_id: str = "") -> None:
  global _data, _held, _logged
  try:
    data = _store()
    done = live.update(started, now, wall_now(), float(v_ego), enabled, state, alert_status, alert_type, drive_id)
    if done is not None:
      _held.append(done)
    if _held and system_time_valid():
      for d in _held:
        data = store.add_drive(data, store.stamp(d, wall_now(), None))
      _data, _held = data, []
      _save()
    elif done is not None or (live.active and now - _saved_t > SAVE_S):
      _save()
  except Exception:
    if not _logged:
      _logged = True
      from openpilot.common.swaglog import cloudlog
      cloudlog.exception("tripstats tick")
