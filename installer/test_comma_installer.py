"""Static checks for the comma setup ELF. This does not run it."""

import hashlib
import struct
from pathlib import Path

from installer.build_comma_installer import BRANCH, NEW_URL, OLD_URL, patch_git_url

ROOT = Path(__file__).resolve().parents[1]
ELF = ROOT / "installer" / "comma-installer"
EXPECTED_SHA256 = "40486647426c251fbb446e410f675533d8cdcb294d86cc083d7757d69b71e6e8"


def test_patch_keeps_size_and_replaces_only_the_url_slot():
  base = OLD_URL + b"?" + b" " * 40 + b"\x00" + BRANCH + b"?" + b" " * 10 + b"\x00tail"
  patched = patch_git_url(base)
  assert len(patched) == len(base)
  assert patched.count(NEW_URL + b"?") == 1
  assert OLD_URL not in patched
  assert patched.count(BRANCH + b"?") == 1
  assert patched.endswith(b"\x00tail")


def test_committed_installer_is_the_aarch64_elf_for_this_repo_and_branch():
  data = ELF.read_bytes()
  assert hashlib.sha256(data).hexdigest() == EXPECTED_SHA256
  assert data[:4] == b"\x7fELF"
  elf_class, elf_data, _, osabi = data[4], data[5], data[6], data[7]
  assert (elf_class, elf_data, osabi) == (2, 1, 3)  # 64-bit, little endian, GNU
  machine = struct.unpack_from("<H", data, 18)[0]
  assert machine == 183  # EM_AARCH64
  assert data.count(NEW_URL + b"?") == 1
  assert OLD_URL not in data
  assert data.count(BRANCH + b"?") == 1
  assert b"https://github.com/commaai/openpilot.git?" not in data
