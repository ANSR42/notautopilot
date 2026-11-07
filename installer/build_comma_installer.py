"""Patch the fork-installer git URL slot in comma's AArch64 installer ELF.

comma's installer.comma.ai always writes https://github.com/<user>/openpilot.git.
This repo is named notautopilot. The installer source leaves a padded string
that ends at '?' (selfdrive/ui/installer/installer.cc). This script replaces
only that URL and keeps the file size and the branch slot unchanged.

It does not send a device-type header, disable a check, or run the installer.
"""

import hashlib
import sys

OLD_URL = b"https://github.com/ANSR42/openpilot.git"
NEW_URL = b"https://github.com/ANSR42/notautopilot.git"
BRANCH = b"cursor/stable-audit-report-1491"


def patch_git_url(data: bytes, old_url: bytes = OLD_URL, new_url: bytes = NEW_URL) -> bytes:
  if len(new_url) < len(old_url):
    raise ValueError("replacement URL is shorter than the slot marker")
  marker = old_url + b"?"
  start = data.find(marker)
  if start < 0 or data.find(marker, start + 1) >= 0:
    raise ValueError("expected exactly one installer git URL slot")
  end = data.find(b"\x00", start)
  if end < 0:
    raise ValueError("git URL slot is not NUL terminated")
  new_marker = new_url + b"?"
  if len(new_marker) > end - start:
    raise ValueError("replacement URL does not fit in the existing slot")
  patched = bytearray(data)
  patched[start:end] = new_marker + b" " * (end - start - len(new_marker))
  if len(patched) != len(data):
    raise ValueError("patch changed the installer size")
  return bytes(patched)


def main(argv: list[str]) -> int:
  if len(argv) != 3:
    print("usage: build_comma_installer.py BASE_ELF OUTPUT_ELF", file=sys.stderr)
    return 2
  base = open(argv[1], "rb").read()
  patched = patch_git_url(base)
  if patched.count(NEW_URL + b"?") != 1 or patched.count(OLD_URL) != 0:
    raise SystemExit("patched installer does not contain exactly the notautopilot URL")
  if patched.count(BRANCH + b"?") != 1:
    raise SystemExit("patched installer lost the branch slot")
  open(argv[2], "wb").write(patched)
  print(hashlib.sha256(patched).hexdigest())
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv))
