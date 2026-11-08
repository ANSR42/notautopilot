from pathlib import Path

ENGAGEMENT_LATCH_NAME = "error.txt"


def write_exception_files(directory: Path, exc_text: str, timestamp_name: str,
                          crash_log: bool, latch_engagement: bool) -> None:
  """Write the timestamped crash log and, when requested, the engagement latch.

  ``error.txt`` is the file starpilot reads to raise ``openpilotCrashed``.
  Callers that are not vehicle control pass ``latch_engagement=False`` so the
  timestamped log is kept and stock cruise can still engage.
  """
  directory = Path(directory)
  (directory / timestamp_name).write_text(exc_text)
  if not latch_engagement:
    return

  latch_path = directory / ENGAGEMENT_LATCH_NAME
  if crash_log:
    latch_path.write_text("\n".join(exc_text.splitlines()[-10:]))
  else:
    latch_path.write_text(exc_text)
