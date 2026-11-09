"""The boot import must resolve the vendored crcmod, not a system package."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / "starpilot" / "third_party" / "crcmod"
THIRD = ROOT / "starpilot" / "third_party"

# Exact bytes from crcmod 1.7 python3/crcmod and LICENSE.
EXPECTED_SHA256 = {
    "__init__.py": "08f018091d5412443ea1d2a67aa374ac45b60d150dc8097de0eec318582fdd6a",
    "crcmod.py": "2ce34d54bd210a16785161d5cae0b91894a4ba8545e8a6f047bb08209a6729db",
    "predefined.py": "6957449a0d0d120463a2aadf33161a92991e814362a77f5ccc7a38a4d71a8f9e",
    "_crcfunpy.py": "046b8a0c3e34a39920235d878e5022ed6951df74031454adaf58bde4652eaa20",
    "test.py": "0723d05a13a369a8261b65081358932a54e7905b6c50c4281a42a3510f7f191a",
    "LICENSE": "89480768826f408daea1f3caff0509c2cc9606e10f6bb0ccfd12a3d604842c35",
}


def test_vendored_files_match_crcmod_1_7_sdist():
    for name, digest in EXPECTED_SHA256.items():
        assert hashlib.sha256((PKG / name).read_bytes()).hexdigest() == digest
    assert b"_crcfunext" not in (PKG / "crcmod.py").read_bytes() or b"ImportError" in (PKG / "crcmod.py").read_bytes()
    assert not (PKG / "_crcfunext.py").exists()


def test_pythonpath_resolves_vendored_crcmod_and_hyundai_polynomial():
    script = r"""
import sys
sys.path.insert(0, sys.argv[1])
for name in list(sys.modules):
    if name == "crcmod" or name.startswith("crcmod."):
        del sys.modules[name]
import crcmod
impl = sys.modules["crcmod.crcmod"]
assert sys.argv[1] in crcmod.__file__, crcmod.__file__
assert impl._usingExtension is False
fn = crcmod.mkCrcFun(0x11D, initCrc=0xFD, rev=False, xorOut=0xdf)
assert fn(b"\x01\x02\x03") == 0xdc
print(crcmod.__file__)
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", script, str(THIRD)],
        check=True, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(THIRD)},
    )
    assert "starpilot/third_party/crcmod" in result.stdout.replace("\\", "/")


def test_upstream_crcmod_unit_tests_pass_without_the_c_extension():
    result = subprocess.run(
        [sys.executable, "-S", "-m", "unittest", "crcmod.test"],
        check=False, capture_output=True, text=True,
        cwd=ROOT, env={**os.environ, "PYTHONPATH": str(THIRD)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stderr or "OK" in result.stdout
