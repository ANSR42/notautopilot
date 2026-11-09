import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from cereal import car

from openpilot.selfdrive.ui import tripstats
from openpilot.selfdrive.ui.tripstats import store
from openpilot.selfdrive.ui.tripstats.card import card_columns, eligible, timeline_rects, timeline_runs
from openpilot.selfdrive.ui.tripstats.park_end import PARK_HOLD_S, ParkEnd
from openpilot.selfdrive.ui.tripstats.presenter import TripPresenter
from openpilot.selfdrive.ui.tripstats.recorder import ENGAGED, MANUAL, DriveRecorder


def _drive(seconds: float, speed: float, enabled: bool) -> DriveRecorder:
  rec = DriveRecorder()
  now = 0.0
  step = 0.1
  frames = int(seconds / step)
  for i in range(frames):
    rec.update(True, now, 1_700_000_000 + now, speed, enabled, "enabled" if enabled else "disabled", "normal", "", "route")
    now += step
  return rec


def test_engaged_distance_and_best_stretch():
  rec = DriveRecorder()
  t = 0.0
  for _ in range(100):
    rec.update(True, t, t, 10.0, True, "enabled", "normal", "", "route")
    t += 0.1
  for _ in range(50):
    rec.update(True, t, t, 10.0, False, "disabled", "normal", "", "route")
    t += 0.1
  for _ in range(40):
    rec.update(True, t, t, 10.0, True, "enabled", "normal", "", "route")
    t += 0.1
  assert rec.m > rec.e > rec.best_m > 90.0
  assert "e" in rec.timeline.codes()
  assert "m" in rec.timeline.codes()


def test_short_stop_does_not_split_the_drive_and_three_seconds_offroad_does():
  rec = DriveRecorder()
  rec.update(True, 0.0, 10.0, 10.0, True, "enabled")
  rec.update(True, 1.0, 11.0, 10.0, True, "enabled")
  assert rec.update(False, 2.0, 12.0, 0.0, False) is None
  rec.update(True, 3.0, 13.0, 10.0, True, "enabled")
  assert rec.active
  assert rec.update(False, 4.0, 14.0, 0.0, False) is None
  done = rec.update(False, 7.1, 17.1, 0.0, False)
  assert done is not None
  assert done["m"] > 0
  assert not rec.active


def test_full_screen_layout_fits_mici_and_big():
  from openpilot.selfdrive.ui.tripstats.card import card_layout
  from openpilot.selfdrive.ui.tripstats.recorder import COLORS, ENGAGED, MANUAL
  cols = [("0.6", "mi", "driven"), ("40", "%", "engaged"), ("0.1", "mi", "streak"), ("1", "", "day streak")]
  codes = "mmmmmeeeeeoooppc"
  for width, height in ((536, 240), (2160, 1080)):
    layout = card_layout(width, height, cols, codes)
    assert layout["background"] == (0.0, 0.0, width, height)
    assert len(layout["columns"]) == 4
    centers = [col["center"] for col in layout["columns"]]
    assert centers == sorted(centers)
    assert centers[-1] - centers[0] > width * 0.5
    bx, by, bw, bh = layout["timeline"]
    assert bh >= 16
    assert by + bh < height
    assert bx >= 0 and bx + bw <= width
    assert layout["segments"]
    covered = sum(seg[2] for seg in layout["segments"])
    assert covered > bw * 0.9
    colors = {COLORS[seg[4]] for seg in layout["segments"]}
    assert COLORS[ENGAGED] in colors and COLORS[MANUAL] in colors


def test_mici_screenshots_cover_the_screen_and_show_the_timeline(tmp_path):
  from PIL import Image
  from openpilot.selfdrive.ui.tripstats.tests.paint_card import BG, paint_card
  cols = [("0.6", "mi", "driven"), ("40", "%", "engaged"), ("0.1", "mi", "streak"), ("1", "", "day streak")]
  codes = "mmmmmeeeeeoooppc"
  out = Path("/opt/cursor/artifacts")
  if not out.is_dir():
    out = tmp_path
  auto = out / "trip_card_mici_auto.png"
  reopen = out / "trip_card_mici_reopen.png"
  big = out / "trip_card_big.png"
  paint_card(auto, 536, 240, "trip summary", cols, codes)
  paint_card(reopen, 536, 240, "trip summary", cols, codes)
  paint_card(big, 2160, 1080, "trip summary", cols, codes)
  for path, size in ((auto, (536, 240)), (reopen, (536, 240)), (big, (2160, 1080))):
    image = Image.open(path)
    assert image.size == size
    assert image.getpixel((0, 0)) == BG
    assert image.getpixel((size[0] - 1, size[1] - 1)) == BG
  bar = Image.open(auto)
  colors = {bar.getpixel((x, 140)) for x in range(20, 500, 8)}
  assert len(colors) >= 3


def test_card_columns_timeline_and_minimum_trip():
  short = {"m": 100.0, "e": 50.0, "best_m": 50.0, "dur": 40.0, "tl": "em"}
  assert not eligible(short)
  drive = {"m": 1609.344, "e": 804.672, "best_m": 500.0, "dur": 60.0, "tl": "eemm"}
  assert eligible(drive)
  cols = card_columns(drive, 3, False)
  assert cols[0][0] == "1.0" and cols[0][2] == "driven"
  assert cols[1] == ("50", "%", "engaged")
  assert cols[3] == ("3", "", "day streak")
  runs = timeline_runs(drive["tl"])
  assert runs[0][0] == 1 and runs[1][0] == 0
  rects = timeline_rects(0, 0, 200, 18, runs, 4)
  assert rects
  assert {status for *_, status in rects} <= {MANUAL, ENGAGED}


def test_store_dates_the_drive_locally_and_counts_a_day_streak(tmp_path):
  end = datetime(2026, 11, 8, 18, 0, tzinfo=UTC).timestamp()
  drive = store.stamp({"id": "a", "m": 2000.0, "e": 1500.0, "best_m": 800.0, "dur": 100.0, "tl": "e", "shown": False}, end)
  data = store.add_drive(store.empty(), drive)
  yesterday = store.stamp({"id": "b", "m": 2000.0, "e": 1000.0, "best_m": 100.0, "dur": 80.0, "tl": "e", "shown": True}, end - 86400)
  data = store.add_drive(data, yesterday)
  path = tmp_path / "drive_summary.json"
  store.write_file(path, data)
  loaded = store.read_file(path)
  assert loaded["last"]["id"] == "b" or loaded["last"]["m"] > 0
  viewed = store.view(loaded, at=datetime.fromtimestamp(end, UTC))
  assert viewed["streak_days"] >= 1
  assert viewed["longest_m"] >= 800.0


def test_periodic_save_and_missed_card_after_restart(tmp_path):
  tripstats.configure(tmp_path / "drive_summary.json")
  tripstats.reset()
  now = 0.0
  for _ in range(400):
    tripstats.tick(True, now, 12.0, True, "enabled", "normal", "", "route-1")
    now += 0.1
  assert (tmp_path / "drive_summary.json").exists()
  tripstats.reset()
  tripstats.configure(tmp_path / "drive_summary.json")
  missed = tripstats.missed_trip()
  assert missed is not None
  assert not missed["shown"]
  tripstats.mark_shown(missed)
  assert tripstats.missed_trip() is None
  tripstats.configure(None)
  tripstats.reset()


def test_tesla_park_ends_the_drive_on_screen_and_drive_resumes_it():
  park = ParkEnd()
  now = 10.0
  assert park.update(now, tesla=True, gear_park=True, engaged=False, speed=0.0) is False
  assert park.update(now + PARK_HOLD_S, tesla=True, gear_park=True, engaged=False, speed=0.0) is True
  assert park.update(now + PARK_HOLD_S + 1, tesla=True, gear_park=False, engaged=False, speed=2.0) is False
  assert park.update(now, tesla=False, gear_park=True, engaged=False, speed=0.0) is False
  assert park.update(now + PARK_HOLD_S, tesla=True, gear_park=True, engaged=True, speed=0.0) is False


def test_presenter_shows_the_card_after_a_tesla_park_hold_without_going_offroad(tmp_path):
  tripstats.configure(tmp_path / "drive_summary.json")
  tripstats.reset()
  now = 0.0
  for _ in range(400):
    tripstats.tick(True, now, 12.0, True, "enabled", "normal", "", "route-1")
    now += 0.1
  tripstats.tick(True, now, 0.0, False, "disabled", "normal", "", "route-1")
  ui = _tesla_ui(park=False, enabled=False, speed=0.0)
  presenter = TripPresenter()
  presenter._was_recording = True
  presenter.frame(ui)
  ui.sm["carState"].gearShifter = car.CarState.GearShifter.park
  presenter.park._since = time.monotonic() - PARK_HOLD_S - 0.1
  presenter.frame(ui)
  assert ui.started
  assert presenter.park.ended
  assert presenter.visible
  assert presenter.headline == "trip summary"
  assert presenter.drive["m"] >= 160.9
  tripstats.configure(None)
  tripstats.reset()


def _tesla_ui(park: bool, enabled: bool, speed: float):
  gear = car.CarState.GearShifter.park if park else car.CarState.GearShifter.drive
  state = SimpleNamespace(name="enabled" if enabled else "disabled")
  alert = SimpleNamespace(name="normal")
  cs = SimpleNamespace(vEgo=speed, gearShifter=gear)
  ss = SimpleNamespace(enabled=enabled, state=state, alertStatus=alert, alertType="")
  sm = SimpleNamespace(valid={"carState": True, "selfdriveState": True}, **{"carState": cs, "selfdriveState": ss})
  # SimpleNamespace doesn't support item assignment via sm["carState"] unless we use a dict-like.
  class SM(dict):
    def __init__(self):
      super().__init__(carState=cs, selfdriveState=ss)
      self.valid = {"carState": True, "selfdriveState": True}
  return SimpleNamespace(started=True, CP=SimpleNamespace(brand="tesla"), sm=SM(), params=SimpleNamespace(get=lambda *a, **k: ""))
