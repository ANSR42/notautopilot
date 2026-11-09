# Ported from TeslaPilot (MIT), Memberoffoxhound/TeslaPilot, branch Highland-Dev.
# https://github.com/Memberoffoxhound/TeslaPilot
# Drive stats stay on this device. Nothing in this module is uploaded.

"""One drive, recorded frame by frame: distance, engaged distance, best stretch, a status timeline.

Pure: no openpilot imports. Constant memory: N_BUCKETS time buckets that merge pairwise (bucket
length doubles) as the drive grows. Engaged percent is by distance.
Colors and priorities are comma connect's route timeline.
"""
from __future__ import annotations

N_BUCKETS = 160
BUCKET_S0 = 2.0
MERGE_S = 3.0
MOVING_V = 0.15

MANUAL, ENGAGED, OVERRIDE, PROMPT, CRITICAL, FLAG = range(6)
CODES = "meopcf"
COLORS = {
  MANUAL: (0x17, 0x58, 0x86),
  ENGAGED: (0x17, 0x86, 0x45),
  OVERRIDE: (0x91, 0x9b, 0x95),
  PROMPT: (0xda, 0x6f, 0x25),
  CRITICAL: (0xc9, 0x22, 0x31),
  FLAG: (0xe3, 0xd7, 0x56),
}

BOOKMARK_S = 1.0
_OVERRIDE_STATES = ("preEnabled", "overriding")


class Layers:
  def __init__(self) -> None:
    self._since: dict[int, tuple[float, str]] = {}
    self._bookmark: float | None = None
    self._in_bookmark = False

  def status(self, t: float, enabled: bool, state: str, alert_status: str, alert_type: str = "") -> int:
    alert = CRITICAL if alert_status == "critical" else PROMPT if alert_status == "userPrompt" else None
    now = {
      ENGAGED: "e" if enabled else None,
      OVERRIDE: state if state in _OVERRIDE_STATES else None,
      PROMPT: "a" if alert == PROMPT else None,
      CRITICAL: "a" if alert == CRITICAL else None,
    }
    for layer, key in now.items():
      if key is None:
        self._since.pop(layer, None)
      elif layer not in self._since or self._since[layer][1] != key:
        self._since[layer] = (t, key)
    bookmark = alert_type.startswith("userBookmark")
    if bookmark and not self._in_bookmark:
      self._bookmark = t
    self._in_bookmark = bookmark
    if self._bookmark is not None and t - self._bookmark < BOOKMARK_S:
      return FLAG
    if not self._since:
      return MANUAL
    tie = (ENGAGED, PROMPT, CRITICAL, OVERRIDE)
    return max(self._since, key=lambda layer: (self._since[layer][0], tie.index(layer)))


class Timeline:
  def __init__(self, n: int = N_BUCKETS, bucket_s: float = BUCKET_S0) -> None:
    self.n = n
    self.bucket_s = bucket_s
    self.t = 0.0
    self.buckets = [[0.0] * 6 for _ in range(n)]

  def _compact(self) -> None:
    half = self.n // 2
    for i in range(half):
      a, b = self.buckets[2 * i], self.buckets[2 * i + 1]
      self.buckets[i] = [x + y for x, y in zip(a, b, strict=True)]
    for i in range(half, self.n):
      self.buckets[i] = [0.0] * 6
    self.bucket_s *= 2.0

  def add(self, status: int, dt: float) -> None:
    while dt > 0:
      idx = int(self.t // self.bucket_s)
      if idx >= self.n:
        self._compact()
        continue
      step = min(dt, (idx + 1) * self.bucket_s - self.t)
      step = max(step, 1e-9)
      self.buckets[idx][status] += step
      self.t += step
      dt -= step

  @staticmethod
  def dominant(b: list[float]) -> int:
    for st in (FLAG, CRITICAL, PROMPT):
      if b[st] > 0:
        return st
    return max((MANUAL, ENGAGED, OVERRIDE), key=lambda s: (b[s], s))

  def codes(self) -> str:
    used = min(self.n, int(-(-self.t // self.bucket_s))) if self.t > 0 else 0
    return "".join(CODES[self.dominant(self.buckets[i])] for i in range(used))


class DriveRecorder:
  def __init__(self) -> None:
    self.active = False
    self._reset()

  def _reset(self) -> None:
    self.m = self.e = 0.0
    self.dur = 0.0
    self.cur_m = self.best_m = 0.0
    self.timeline = Timeline()
    self.layers = Layers()
    self.drive_id = ""
    self.start_wall = 0.0
    self._t: float | None = None
    self._off_since: float | None = None
    self._off_wall = 0.0
    self.last_v = 0.0
    self.shown = False

  def update(self, started: bool, now: float, wall: float, v_ego: float, enabled: bool,
             state: str = "", alert_status: str = "normal", alert_type: str = "",
             drive_id: str = "") -> dict | None:
    if started:
      if not self.active:
        self._reset()
        self.active = True
        self.start_wall = wall
        self.drive_id = drive_id or f"t{int(wall)}"
      elif self._off_since is not None:
        self._off_since = None
        self._t = now
      elif drive_id and self.drive_id.startswith("t"):
        self.drive_id = drive_id
      dt = 0.0 if self._t is None else min(1.0, max(0.0, now - self._t))
      self._t = now
      self.last_v = v_ego
      d = v_ego * dt if v_ego > MOVING_V else 0.0
      self.m += d
      self.dur += dt
      if enabled:
        self.e += d
        self.cur_m += d
        self.best_m = max(self.best_m, self.cur_m)
      else:
        self.cur_m = 0.0
      if dt > 0:
        self.timeline.add(self.layers.status(self.dur, enabled, state, alert_status, alert_type), dt)
      return None
    if self.active:
      if self._off_since is None:
        self._off_since, self._off_wall = now, wall
      if now - self._off_since >= MERGE_S:
        self.active = False
        self._off_since = None
        return self.summary(self._off_wall)
    return None

  def summary(self, end_wall: float) -> dict:
    return {
      "id": self.drive_id, "start": self.start_wall, "end": end_wall, "dur": round(self.dur, 1),
      "m": round(self.m, 1), "e": round(self.e, 1), "best_m": round(self.best_m, 1),
      "tl": self.timeline.codes(), "shown": self.shown,
    }
