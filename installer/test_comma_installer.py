"""Static checks for the comma setup ELF. This does not run it."""

import hashlib
import struct
from pathlib import Path

from installer.build_comma_installer import BRANCH, NEW_URL, OLD_BRANCH, OLD_URL, patch_branch, patch_git_url

ROOT = Path(__file__).resolve().parents[1]
ELF = ROOT / "installer" / "comma-installer"
EXPECTED_SHA256 = "c32b709367745d95b252cff18cc2c6e3606722c10c5a5e0b240f593cc78266a5"


def test_patch_branch_keeps_the_notautopilot_url_slot():
  base = NEW_URL + b"?" + b" " * 20 + b"\x00" + OLD_BRANCH + b"?" + b" " * 40 + b"\x00tail"
  patched = patch_branch(base)
  assert len(patched) == len(base)
  assert patched.count(BRANCH + b"?") == 1
  assert OLD_BRANCH not in patched
  assert patched.count(NEW_URL + b"?") == 1


def test_patch_keeps_size_and_replaces_only_the_url_slot():
  base = OLD_URL + b"?" + b" " * 40 + b"\x00" + BRANCH + b"?" + b" " * 10 + b"\x00tail"
  patched = patch_git_url(base)
  assert len(patched) == len(base)
  assert patched.count(NEW_URL + b"?") == 1
  assert OLD_URL not in patched
  assert patched.count(BRANCH + b"?") == 1
  assert patched.endswith(b"\x00tail")


def test_dynamic_section_needs_adreno_gles_and_gbm():
  import subprocess
  output = subprocess.run(["readelf", "-d", str(ELF)], check=True, capture_output=True, text=True).stdout
  needed = [line.split("[", 1)[1].rstrip("]") for line in output.splitlines() if "(NEEDED)" in line]
  assert needed == [
    "libGLESv2_adreno.so",
    "libEGL_adreno.so",
    "libgbm.so",
    "libstdc++.so.6",
    "libm.so.6",
    "libgcc_s.so.1",
    "libc.so.6",
  ]
  interp = subprocess.run(["readelf", "-l", str(ELF)], check=True, capture_output=True, text=True).stdout
  assert "/lib/ld-linux-aarch64.so.1" in interp


def test_starpilot_bundled_setup_cannot_name_notautopilot():
  import re
  source = (ROOT / "tools/agnos/patch_system_reset_image.py").read_text(encoding="utf-8")
  assert "installer.comma.ai binary targets Wayland and cannot run in this AGNOS." in source
  assert 'f"https://github.com/{owner}/openpilot.git"' in source
  assert "re.fullmatch" in source
  # The pattern the patched setup evaluates. A branch slash does not match.
  pattern = re.compile(r"(?:https://installer\.comma\.ai/)?([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+)")
  raw_url = "https://raw.githubusercontent.com/ANSR42/notautopilot/cursor/stable-audit-report-1491/installer/comma-installer"
  assert pattern.fullmatch(raw_url) is None
  assert pattern.fullmatch("https://installer.comma.ai/ANSR42/cursor/stable-audit-report-1491") is None
  assert pattern.fullmatch("https://installer.comma.ai/ANSR42/notautopilot").groups() == ("ANSR42", "notautopilot")


def _version_tuple(text: str) -> tuple[int, ...]:
  return tuple(int(part) for part in text.split("."))


def test_needed_glibc_is_within_the_measured_19_9_loader():
  import re
  import subprocess
  output = subprocess.run(["readelf", "-V", str(ELF)], check=True, capture_output=True, text=True).stdout
  glibc = {_version_tuple(match) for match in re.findall(r"GLIBC_([0-9.]+)", output)}
  cxx = {_version_tuple(match) for match in re.findall(r"GLIBCXX_([0-9.]+)", output)}
  assert glibc
  assert max(glibc) <= (2, 39)
  assert max(cxx) <= (3, 4, 30)


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
  assert BRANCH == b"cursor/alc-test-install-1491"
  assert OLD_BRANCH not in data
  assert b"https://github.com/commaai/openpilot.git?" not in data


def test_launch_accepts_measured_agnos_19_9_without_replacing_the_build_pin():
  text = (ROOT / "launch_env.sh").read_text(encoding="utf-8")
  assert 'export AGNOS_VERSION="19.8.1"' in text
  assert "19.9" in text.split("AGNOS_ACCEPTED_VERSIONS=", 1)[1].split("\n", 1)[0]
