# Ported from TeslaPilot (MIT), Memberoffoxhound/TeslaPilot, branch Highland-Dev.
# https://github.com/Memberoffoxhound/TeslaPilot
# The store is one JSON file on this device. It is not a param and it is not uploaded.

"""Per-day totals and the numbers the trip card shows.

Days use the device clock's local date. Week rows start on Sunday. This port does not
ship tzgrid.bin or weekstart.json.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path

VER = 2
DAYS_KEEP = 400
STREAK_E = 1.0


def default_path() -> Path:
  data = Path("/data")
  if data.is_dir():
    return data / "notautopilot" / "drive_summary.json"
  return Path.home() / ".notautopilot" / "drive_summary.json"


def offset(wall: float, zone: tzinfo | None = None) -> int:
  delta = datetime.fromtimestamp(wall, UTC).astimezone(zone).utcoffset()
  return int(delta.total_seconds()) if delta is not None else 0


def day_key(end: float, off: int) -> str:
  return datetime.fromtimestamp(end + off, UTC).date().isoformat()


def stamp(drive: dict, wall: float, zone: tzinfo | None = None, ok: bool = True) -> dict:
  return {**drive, "end": wall, "off": offset(wall, zone), "ok": ok}


def engaged_pct(eng: float, meters: float) -> int:
  return int(round(100.0 * eng / meters)) if meters > 1 else 0


def _try(fn, *args):
  try:
    return fn(*args)
  except Exception:
    return None


def _pair(v) -> list[float]:
  return [float(v[0]), float(v[1])]


def _day(k: str, v) -> list[float]:
  date.fromisoformat(k)
  return _pair(v)


def _drive(d) -> dict:
  return {
    **d, "m": float(d["m"]), "e": float(d["e"]), "best_m": float(d.get("best_m") or 0),
    "end": float(d["end"]), "off": int(d["off"]), "ok": bool(d.get("ok")),
  }


def empty() -> dict:
  return {"v": VER, "days": {}, "life": [0.0, 0.0], "record_m": 0.0, "streak_max": 0, "open": []}


def load_data(raw: dict | None) -> dict:
  data = empty()
  raw = raw or {}
  if raw.get("v") != VER:
    return data
  for k, v in _try(lambda: list(raw["days"].items())) or []:
    if (pair := _try(_day, k, v)) is not None:
      data["days"][k] = pair
  data["life"] = _try(_pair, raw.get("life")) or data["life"]
  data["record_m"] = _try(float, raw.get("record_m")) or 0.0
  data["streak_max"] = _try(int, raw.get("streak_max")) or 0
  data["open"] = [d for o in _try(list, raw.get("open")) or [] if (d := _try(_drive, o))]
  if (last := _try(_drive, raw.get("last"))) is not None:
    data["last"] = last
  return data


def read_file(path: Path) -> dict:
  try:
    return load_data(json.loads(path.read_text(encoding="utf-8")))
  except (OSError, json.JSONDecodeError, TypeError):
    return empty()


def write_file(path: Path, data: dict) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  tmp = path.with_suffix(".json.tmp")
  tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
  os.replace(tmp, path)


def add_drive(data: dict, drive: dict) -> dict:
  m, e = drive["m"], drive["e"]
  k = day_key(drive["end"], drive["off"])
  cut = (date.fromisoformat(k) - timedelta(days=DAYS_KEEP)).isoformat()
  days = {d: v for d, v in data["days"].items() if d > cut}
  m0, e0 = days.get(k, (0.0, 0.0))
  days[k] = [round(m0 + m, 1), round(e0 + e, 1)]
  return {
    **data, "days": days,
    "life": [round(data["life"][0] + m, 1), round(data["life"][1] + e, 1)],
    "record_m": round(max(data["record_m"], drive["best_m"]), 1),
    "streak_max": max(data["streak_max"], streaks(days, date.fromisoformat(k))[1]),
    "last": drive,
  }


def streaks(days: dict, today: date) -> tuple[int, int]:
  on = {date.fromisoformat(k) for k, (_, e) in days.items() if e > STREAK_E}
  longest = 0
  for d in on:
    if d - timedelta(days=1) not in on:
      n = 1
      while d + timedelta(days=n) in on:
        n += 1
      longest = max(longest, n)
  d, cur = (today if today in on else today - timedelta(days=1)), 0
  while d in on:
    d, cur = d - timedelta(days=1), cur + 1
  return cur, longest


def view(data: dict, open_drives=(), at: datetime | None = None, zone: tzinfo | None = None, first: int = 6) -> dict:
  now = (at or datetime.now(UTC)).timestamp()
  for d in open_drives:
    data = add_drive(data, stamp(d, now, zone))
  days = data["days"]
  today = date.fromisoformat(day_key(now, offset(now, zone)))
  start = today - timedelta(days=(today.weekday() - first) % 7)
  week = []
  for k in ((start + timedelta(days=i)).isoformat() for i in range(7)):
    m, e = days.get(k, (0.0, 0.0))
    week.append({"id": k, "m": m, "e": e})
  tm, te = days.get(today.isoformat(), (0.0, 0.0))
  (lm, le), (cur, longest) = data["life"], streaks(days, today)
  return {
    "today_m": tm, "today_e": te, "today_pct": engaged_pct(te, tm),
    "week_days": week,
    "life_m": lm, "life_e": le, "pct": engaged_pct(le, lm), "longest_m": data["record_m"],
    "streak_days": max(data["streak_max"], longest), "streak_now": cur,
  }
