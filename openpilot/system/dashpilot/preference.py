"""On/off switch for the DashPilot ZMQ bridge.

The switch is a file, not a Params key. Params.clearAll deletes files that
are not in the compiled key registry, and this tree ships a prebuilt
libparams_c.so. A new key would stay unknown until that library is rebuilt
on the device, which a prebuilt checkout does not do.

Absent, unreadable, or any value other than 0 means on. Write 0 to turn the
bridge off; manager stops it on the next deviceState cycle (about a second).

On a comma the file is /data/starpilot/dashpilot-zmq.
"""

from pathlib import Path

from openpilot.common.utils import atomic_write


FLAG_NAME = "dashpilot-zmq"


def flag_path(path: Path | None = None) -> Path:
  if path is not None:
    return path
  # Imported lazily so a unit test of the switch does not load cereal.
  from openpilot.starpilot.storage import starpilot_storage_root

  return starpilot_storage_root() / FLAG_NAME


def enabled(path: Path | None = None) -> bool:
  try:
    return flag_path(path).read_text().strip() != "0"
  except (OSError, UnicodeError):
    return True


def set_enabled(value: bool, path: Path | None = None) -> bool:
  target = flag_path(path)
  try:
    target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with atomic_write(str(target), overwrite=True) as handle:
      handle.write("1" if value else "0")
  except OSError:
    return False
  return enabled(target) is value
