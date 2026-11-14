"""
The prebuilt tree ships openpilot/common/libparams_c.so. Keys are compiled
into that library from params_keys.h, so a header-only addition crashes
params.get on device. This checks the shipped blob, without loading it.
"""
import re
import unittest
from pathlib import Path

COMMON = Path(__file__).resolve().parents[1]
OPENPILOT = COMMON.parent
HEADER = COMMON / "params_keys.h"
LIBRARY = COMMON / "libparams_c.so"
KEY_RE = re.compile(r'\{\s*"([A-Za-z0-9_]+)"\s*,')
READ_RE = re.compile(
  r'(?:params|Params\(\))\.(?:get(?:_bool|_type)?|put(?:_bool)?|remove)\(\s*"([A-Za-z0-9_]+)"'
)
IDENT = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")
SKIP_PARTS = {"tests", "gen", "third_party", "__pycache__"}


def header_keys() -> list[str]:
  return KEY_RE.findall(HEADER.read_text())


def key_in_library(blob: bytes, key: str) -> bool:
  needle = key.encode()
  start = 0
  while True:
    index = blob.find(needle, start)
    if index < 0:
      return False
    after = blob[index + len(needle):index + len(needle) + 1]
    if not after or after[0] not in IDENT:
      return True
    start = index + 1


def keys_read_by_code() -> set[str]:
  found = set()
  for path in OPENPILOT.rglob("*"):
    if path.suffix not in {".py", ".cc", ".h", ".cpp"} or not path.is_file():
      continue
    if SKIP_PARTS.intersection(path.parts):
      continue
    text = path.read_text(errors="ignore")
    found.update(READ_RE.findall(text))
  return found


class TestShippedParamsLib(unittest.TestCase):
  def test_header_keys_are_in_the_shipped_library(self):
    blob = LIBRARY.read_bytes()
    self.assertEqual(LIBRARY.suffix, ".so")
    missing = [key for key in header_keys() if not key_in_library(blob, key)]
    self.assertEqual(missing, [], f"rebuild openpilot/common/libparams_c.so; missing {missing}")

  def test_code_reads_only_known_keys(self):
    known = set(header_keys())
    unknown = sorted(keys_read_by_code() - known)
    self.assertEqual(unknown, [], f"params keys read by code but not registered: {unknown}")

  def test_path_steering_default_is_off(self):
    text = HEADER.read_text()
    self.assertIn('{"PathSteering", {PERSISTENT | BACKUP, BOOL, "0"}}', text)
    self.assertTrue(key_in_library(LIBRARY.read_bytes(), "PathSteering"))
