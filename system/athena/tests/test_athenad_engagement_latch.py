from pathlib import Path

from openpilot.system.athena.crash_policy import ATHENA_LATCHES_ENGAGEMENT
from openpilot.system.error_log_files import ENGAGEMENT_LATCH_NAME, write_exception_files

ATHENA_TRACE = """\
Traceback (most recent call last):
  File "/data/openpilot/system/athena/athenad.py", line 30, in <module>
    from jsonrpc import JSONRPCResponseManager, dispatcher
ModuleNotFoundError: No module named 'jsonrpc'
"""


def test_athena_does_not_arm_engagement_latch():
  assert ATHENA_LATCHES_ENGAGEMENT is False


def test_athena_crash_keeps_timestamped_log_without_error_txt(tmp_path: Path):
  write_exception_files(
    tmp_path,
    ATHENA_TRACE,
    "2026-11-08--15-15-00.log",
    crash_log=True,
    latch_engagement=ATHENA_LATCHES_ENGAGEMENT,
  )

  stamped = (tmp_path / "2026-11-08--15-15-00.log").read_text()
  assert "No module named 'jsonrpc'" in stamped
  assert not (tmp_path / ENGAGEMENT_LATCH_NAME).exists()


def test_control_crash_still_writes_engagement_latch(tmp_path: Path):
  write_exception_files(
    tmp_path,
    "controlsd\n" + ("x\n" * 12) + "final line\n",
    "2026-11-08--15-15-01.log",
    crash_log=True,
    latch_engagement=True,
  )

  latch = (tmp_path / ENGAGEMENT_LATCH_NAME).read_text().splitlines()
  assert latch[-1] == "final line"
  assert len(latch) == 10
  assert "controlsd" not in (tmp_path / ENGAGEMENT_LATCH_NAME).read_text()


def test_athena_crash_does_not_clear_an_existing_control_latch(tmp_path: Path):
  latch = tmp_path / ENGAGEMENT_LATCH_NAME
  latch.write_text("controlsd failed\n")

  write_exception_files(
    tmp_path,
    ATHENA_TRACE,
    "2026-11-08--15-15-02.log",
    crash_log=True,
    latch_engagement=ATHENA_LATCHES_ENGAGEMENT,
  )

  assert latch.read_text() == "controlsd failed\n"
